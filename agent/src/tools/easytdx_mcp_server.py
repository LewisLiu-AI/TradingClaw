#!/usr/bin/env python3
"""easy-tdx MCP Server — expose 通达信 A股行情数据 as MCP tools for trading-claw.

Thin stdio MCP wrapper around the easy-tdx CLI
(https://github.com/handsomejustin/easy_tdx). The CLI is the project's
documented agent-facing surface (JSON on stdout, progress on stderr), so every
tool shells out to ``python -m easy_tdx <cmd>`` with the same venv interpreter
and parses stdout as JSON. Subprocess isolation means a hung TDX connection
degrades to a timeout error instead of blocking the host agent.

Deployment (production server /opt/vibe-trading):
    venv/bin/pip install easy-tdx          # the only extra dependency
Registered in the operator config /var/lib/vibe/.vibe-trading/agent.json:
    "easytdx": {
        "type": "stdio",
        "command": "/opt/vibe-trading/venv/bin/python",
        "args": ["-m", "src.tools.easytdx_mcp_server"],
        "toolTimeout": 120
    }
Tools surface inside trading-claw sessions as ``mcp_easytdx_<tool>``.
See agent/src/skills/easy-tdx/SKILL.md for the usage policy (when to reach for
these tools vs the built-in loaders).

All tools are read-only market data. No trading, no writes, no API key.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

mcp = FastMCP(
    name="easytdx",
    instructions=(
        "通达信协议 A股/港股/美股 行情数据（免费、无 Key、无需通达信客户端）。"
        "symbol 统一格式：6位代码即可（000001/600519），自动识别市场；"
        "也可显式 'SZ 000001' / '600519.SH'。所有输出为 JSON。"
    ),
)

_DEFAULT_TIMEOUT = float(os.environ.get("EASY_TDX_TIMEOUT", "90"))
_READ_ONLY = {"readOnlyHint": True}

# 代码前缀 → 默认市场。显式给 SH/SZ/BJ 前缀时以显式为准。
_PREFIX_MARKET: tuple[tuple[str, ...], str] = (
    (("6", "9", "5", "11"), "SH"),
    (("0", "3", "12", "15", "16", "18"), "SZ"),
    (("4", "8"), "BJ"),
)


def parse_symbol(symbol: str) -> tuple[str, str]:
    """Normalize a symbol to a (market, code) pair.

    Accepts ``SZ 000001``, ``sz000001``, ``000001.SZ``, ``000001``. Bare
    6-digit codes are routed by exchange-prefix heuristics (60x/68x → SH,
    00x/30x → SZ, 4x/8x → BJ, 11x 可转债 → SH, 12x/15x/16x → SZ).
    """
    s = symbol.strip().upper().replace(".", " ").replace(":", " ")
    tokens = s.split()
    market: str | None = None
    code: str | None = None
    if len(tokens) >= 2 and tokens[0] in ("SH", "SZ", "BJ"):
        market, code = tokens[0], tokens[1]
    elif len(tokens) >= 2 and tokens[-1] in ("SH", "SZ", "BJ"):
        market, code = tokens[-1], tokens[0]
    else:
        joined = "".join(tokens)
        code = joined
        for affix in ("SH", "SZ", "BJ"):
            if joined.startswith(affix) and len(joined) > len(affix):
                market, code = affix, joined[len(affix):]
                break
            if joined.endswith(affix) and len(joined) > len(affix):
                market, code = affix, joined[:-len(affix)]
                break
    if market is None:
        for prefixes, resolved in _PREFIX_MARKET:
            if code.startswith(prefixes):
                market = resolved
                break
    if market is None or not code:
        raise ToolError(f"无法识别的代码 '{symbol}'；示例: 000001 / 600519 / 'SZ 000001' / '600519.SH'")
    return market, code


def parse_symbols(stocks: str) -> str:
    """Normalize a comma-separated multi-symbol string for ``quote``."""
    return ",".join(" ".join(parse_symbol(part)) for part in stocks.split(",") if part.strip())


def _round_floats(value: Any, digits: int = 6) -> Any:
    """Trim float32 noise from TDX protocol fields (11.8900003433 → 11.89)."""
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, list):
        return [_round_floats(item, digits) for item in value]
    if isinstance(value, dict):
        return {key: _round_floats(item, digits) for key, item in value.items()}
    return value


def _run_cli(args: list[str], *, timeout: float | None = None) -> Any:
    """Run ``python -m easy_tdx <args>`` and return parsed stdout JSON."""
    timeout = timeout or _DEFAULT_TIMEOUT
    argv = [sys.executable, "-m", "easy_tdx", *args]
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"easy-tdx {' '.join(args)} 超时（>{timeout:.0f}s），行情服务器可能不可达；可用 ping 工具诊断") from None
    except OSError as exc:
        raise ToolError(f"easy-tdx CLI 启动失败（需 pip install easy-tdx）: {exc}") from None

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
        raise ToolError(f"easy-tdx {' '.join(args)} 退出码 {proc.returncode}: {' | '.join(tail)}")
    try:
        return _round_floats(json.loads(proc.stdout))
    except json.JSONDecodeError:
        tail = (proc.stdout or "").strip().splitlines()[-5:]
        raise ToolError(f"easy-tdx {' '.join(args)} 输出不是 JSON: {' | '.join(tail)}") from None


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


# --- 连通性 ---


@mcp.tool(annotations=_READ_ONLY)
def ping() -> Any:
    """测试通达信行情服务器连通性并测速，返回各服务器延迟(ms)列表。

    当其他 easytdx 工具超时/报错时先用它诊断网络。耗时约 10-20 秒。
    """
    return _run_cli(["ping"])


# --- 行情 ---


@mcp.tool(annotations=_READ_ONLY)
def quote(stocks: str) -> Any:
    """获取 A股实时报价快照（支持多只，逗号分隔）。

    stocks 示例: "000001,600519" 或 "SZ 000001,SH 600519"。
    返回: name/open/high/low/close/vol/amount/turnover(换手%)/pe_ttm/
    pe_dynamic/total_market_cap_ab(总市值)/main_net_amount(主力净流入)/
    dividend_yield 等。盘中为实时价，收盘后为全天快照。
    """
    return _run_cli(["quote", parse_symbols(stocks)])


@mcp.tool(annotations=_READ_ONLY)
def kline(
    symbol: str,
    period: str = "DAILY",
    count: int = 120,
    adjust: str = "NONE",
    bar_time: str | None = None,
) -> Any:
    """获取 K 线 OHLCV 历史。

    symbol: 6位代码。period: DAILY/1MIN/5MIN/15MIN/30MIN/60MIN/WEEKLY/MONTHLY。
    count: 条数(≤800，默认120)。adjust: NONE/QFQ(前复权)/HFQ(后复权)。
    bar_time: 仅分钟级有效，end=右端点时间戳(对齐Tushare/同花顺)。
    返回: [{datetime, open, high, low, close, vol, amount, ...}] 按时间升序。
    """
    args = ["kline", *parse_symbol(symbol), "--period", period.upper(),
            "--count", str(_clamp(count, 1, 800)), "--adjust", adjust.upper()]
    if bar_time:
        args += ["--bar-time", bar_time]
    return _run_cli(args)


@mcp.tool(annotations=_READ_ONLY)
def quote_list(
    category: str = "A",
    count: int = 30,
    sort: str = "CHANGE_PCT",
    order: str = "DESC",
) -> Any:
    """市场分类报价排行（实时榜单）。

    category: A/B/SH/SZ/KCB(科创)/CYB(创业)/BJ/ETF/LOF/HGT(沪股通)/SGT(深股通)。
    sort: CHANGE_PCT/PRICE/VOLUME/TOTAL_AMOUNT/TURNOVER_RATE。
    用途: 全市场涨幅榜、成交额榜、换手率榜、板块异动时的个股联动排查。
    """
    return _run_cli(["quote-list", category.upper(), "--count", str(_clamp(count, 1, 100)),
                    "--sort", sort.upper(), "--order", order.upper()])


@mcp.tool(annotations=_READ_ONLY)
def tick(symbol: str, date: int | None = None, days: int | None = None) -> Any:
    """获取分时图数据（当日或指定日期，最多5日）。

    date: YYYYMMDD；days: 1 或 5（最近N个交易日）。
    """
    args = ["tick", *parse_symbol(symbol)]
    if date:
        args += ["--date", str(date)]
    if days:
        args += ["--days", str(_clamp(days, 1, 5))]
    return _run_cli(args)


@mcp.tool(annotations=_READ_ONLY)
def transaction(symbol: str, count: int = 200, date: int | None = None) -> Any:
    """获取逐笔成交数据（大单动向、尾盘异动分析用）。

    date: YYYYMMDD（默认今天）。count ≤ 2000。
    """
    args = ["transaction", *parse_symbol(symbol), "--count", str(_clamp(count, 1, 2000))]
    if date:
        args += ["--date", str(date)]
    return _run_cli(args)


# --- 板块 ---


@mcp.tool(annotations=_READ_ONLY)
def board_ranking(
    board_type: str = "HY",
    top: int = 15,
    sort_by: str | None = None,
    asc: bool = False,
) -> Any:
    """行业/概念板块涨跌排行榜（含板块成交额与主力净流入）。

    board_type: HY(行业)/GN(概念)。sort_by: change_pct/amount/main_net_amount/vol。
    用途: 判断当日市场主线（哪些行业/概念领涨领跌、资金流向哪些板块）。
    """
    args = ["board-ranking", "--type", board_type.upper(), "--top", str(_clamp(top, 1, 100))]
    if sort_by:
        args += ["--sort-by", sort_by]
    if asc:
        args.append("--asc")
    return _run_cli(args)


@mcp.tool(annotations=_READ_ONLY)
def board_members(board_symbol: str, count: int = 30, sort: str = "CHANGE_PCT") -> Any:
    """获取板块成分股实时报价。

    board_symbol: 板块代码（881xxx 行业 / 880xxx 概念，从 board_ranking 获得）。
    用途: 板块热度确认后下钻看龙头与补涨标的。
    """
    return _run_cli(["board-members", board_symbol, "--count", str(_clamp(count, 1, 300)),
                    "--sort", sort.upper()])


@mcp.tool(annotations=_READ_ONLY)
def belong_board(symbol: str) -> Any:
    """查询个股所属的行业/概念板块列表。选股反查、同板块联动分析用。"""
    return _run_cli(["belong-board", *parse_symbol(symbol)])


# --- 市场情绪 / 资金 ---


@mcp.tool(annotations=_READ_ONLY)
def market_stat() -> Any:
    """A股全市场统计概况: 涨/跌/平/停牌家数、涨停/跌停家数、总成交额与总市值。

    用途: 一眼看市场情绪（赚钱效应、涨跌比、是否极端行情），零参数。
    """
    return _run_cli(["market-stat"])


@mcp.tool(annotations=_READ_ONLY)
def unusual(market: str = "SZ", count: int = 100) -> Any:
    """市场异动监控: 封涨停/封跌停/炸板/快速拉升/跳水等事件流。

    market: SZ/SH。返回 [{time, code, name, desc, value, unusual_type}]。
    用途: 盘中捕捉异动个股、复盘涨停潮/跌停潮结构。
    """
    return _run_cli(["unusual", market.upper(), "--count", str(_clamp(count, 1, 500))])


@mcp.tool(annotations=_READ_ONLY)
def capital_flow(symbol: str) -> Any:
    """个股当日资金流向: 主力/大/中/小单的流入流出与净额。

    注意口径: 通达信"主力净流入"与东财/同花顺口径不同，与其他数据源
    交叉验证时不可直接对比，只能看自身相对变化趋势。
    """
    return _run_cli(["capital-flow", *parse_symbol(symbol)])


# --- 技术分析 ---


@mcp.tool(annotations=_READ_ONLY)
def indicator(
    indicators: str,
    symbol: str,
    period: str = "DAILY",
    count: int = 60,
    adjust: str = "QFQ",
    params: str | None = None,
) -> Any:
    """计算技术指标（内置34个: MACD/KDJ/RSI/BOLL/MA/EMA/ATR/CCI/OBV…）。

    indicators: 逗号分隔，如 "MACD,KDJ,RSI"。params: "SHORT=10,LONG=22" 或
    "MACD.SHORT=10"。返回每根K线的指标值（默认不含OHLCV，需要配合 kline 工具）。
    """
    args = ["indicator", indicators.upper(), "-m", parse_symbol(symbol)[0],
            "-c", parse_symbol(symbol)[1], "--period", period.upper(),
            "--count", str(_clamp(count, 1, 500)), "--adjust", adjust.upper(), "--no-ohlcv"]
    if params:
        args += ["--params", params]
    return _run_cli(args)


@mcp.tool(annotations=_READ_ONLY)
def chanlun(
    symbol: str,
    period: str = "DAILY",
    count: int = 200,
    adjust: str = "QFQ",
    multi_level: str | None = None,
) -> Any:
    """缠论结构分析: 分型/笔/线段/中枢/买卖点(一二三类)/背驰。

    multi_level: 指定次级别联立分析，如 "30MIN"（日线笔下的30分钟结构）。
    返回 {bis:[笔], zs:[中枢], mmd:[买卖点], bc:[背驰], ...}。
    用途: 趋势结构判断、买卖点定位。
    """
    args = ["chanlun", *parse_symbol(symbol), "--period", period.upper(),
            "--count", str(_clamp(count, 10, 800)), "--adjust", adjust.upper()]
    if multi_level:
        args += ["--multi-level", multi_level.upper()]
    return _run_cli(args)


@mcp.tool(annotations=_READ_ONLY)
def symbol_info(symbol: str) -> Any:
    """个股简要特征快照: 现价、内外盘、均价、换手、动量等单条汇总。"""
    return _run_cli(["symbol-info", *parse_symbol(symbol)])


# --- 基本面 / 公告 ---


@mcp.tool(annotations=_READ_ONLY)
def finance_info(symbol: str) -> Any:
    """最新财务快照（通达信协议，30+ 单期指标）: 股本结构、净资产、
    股东户数、IPO日期、所属省份行业等。"""
    return _run_cli(["finance-info", *parse_symbol(symbol)])


@mcp.tool(annotations=_READ_ONLY)
def announcement(code: str, count: int = 20, page: int = 1) -> Any:
    """检索公司公告（巨潮资讯网，HTTP 数据源，不依赖 TDX 连接）。

    code: 6位代码。返回公告标题/日期/链接列表。
    用途: 排查个股异动对应的事件（增减持、重组、问询函等）。
    """
    return _run_cli(["announcement", code, "--count", str(_clamp(count, 1, 100)),
                    "--page", str(_clamp(page, 1, 50))])


@mcp.tool(annotations=_READ_ONLY)
def f10(code: str, report_type: str = "lrb", num: int = 8) -> Any:
    """财报三表（新浪数据源）: lrb=利润表 / fzb=资产负债表 / llb=现金流量表。

    code: 6位代码。num: 返回期数(≤40)。用途: 财务基本面快速核对。
    """
    return _run_cli(["f10", code, "--type", report_type.lower(), "--num", str(_clamp(num, 1, 40))])


def main() -> None:
    """Entrypoint for stdio MCP (``python -m src.tools.easytdx_mcp_server``)."""
    mcp.run()


if __name__ == "__main__":
    main()
