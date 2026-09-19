#!/usr/bin/env python3
"""Build AI-Berkshire user skills for TradingClaw.

Fetches skills from https://github.com/xbtlin/ai-berkshire (shallow clone,
cached under /tmp) and writes each one into scripts/user-skills/<name>/SKILL.md
with three TradingClaw-specific additions:

1. Frontmatter (name / category / description with trigger words) so the
   SkillsLoader picks it up and the agent triggers it in chat.
2. A "TradingClaw 数据加速层" blockquote inserted right after the H1:
   data lookups MUST prefer the agent's built-in data tools (faster and more
   stable than web scraping); the skill's original fetch instructions become
   the fallback. Each skill gets a tailored tool table.
3. An output rule: full Markdown report is saved AND returned as the final
   chat reply — the Feishu channel renders replies as cards and shards
   oversized ones automatically.

The upstream body itself is kept byte-identical, so re-running this script
against a newer upstream tag is a clean regen. The berkshire router skill
(scripts/user-skills/berkshire/) is hand-maintained and NOT generated here.

Usage:
    python3 scripts/build_berkshire_skills.py [--source /path/to/ai-berkshire]
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "scripts" / "user-skills"
DEFAULT_SOURCE = Path("/tmp/ai-berkshire")
UPSTREAM_URL = "https://github.com/xbtlin/ai-berkshire"

# ---------------------------------------------------------------------------
# Per-skill metadata: 用途 / 适合场景 are quoted verbatim from the upstream
# README capability table (they also feed the berkshire router skill list).
# data: rows for the acceleration table; None → no data block (pure thinking /
# writing tools). trigger: extra chat trigger words beyond the skill name.
# ---------------------------------------------------------------------------

SKILLS: dict[str, dict] = {
    # ── 深度研究类 ───────────────────────────────────────────────────────
    "investment-research": {
        "purpose": "四大师综合深度分析",
        "scenario": "对一家上市公司进行全方位投资研究",
        "category": "analysis",
        "trigger": "投资研究/深度研究/四大师/巴菲特分析/研究这家公司/全面分析",
        "data": [
            ("公司基本面速览（美股/港股估值+分析师）", "`get_stock_profile`"),
            ("A股财务报表/指标（年报、季报）", "`get_financial_statements`"),
            ("美股财报与 SEC 原文（10-K/10-Q/XBRL）", "`get_sec_filings`"),
            ("A股券商研报与一致预期", "`get_research_reports`"),
            ("公司新闻与公告", "`get_stock_news`"),
            ("行情 OHLCV（含复权）", "`get_market_data`"),
            ("精确财务计算/交叉验证（Decimal）", "`financial_rigor`（calc / cross_validate / verify_valuation）"),
        ],
    },
    "investment-team": {
        "purpose": "多Agent并行投研团队",
        "scenario": "4个Agent并行研究，最快速、最全面",
        "category": "analysis",
        "trigger": "投研团队/并行研究/团队分析/快速深度研究",
        "data": [
            ("公司基本面速览（美股/港股）", "`get_stock_profile`"),
            ("A股财务报表/指标", "`get_financial_statements`"),
            ("美股财报与 SEC 原文", "`get_sec_filings`"),
            ("A股券商研报与一致预期", "`get_research_reports`"),
            ("公司新闻", "`get_stock_news`"),
            ("精确财务计算/交叉验证", "`financial_rigor`"),
            ("注意：4 个并行 Agent 取数时同样遵守本节优先级", ""),
        ],
    },
    "management-deep-dive": {
        "purpose": "管理层纵深研究",
        "scenario": "“买股票就是买人”——当管理层是核心变量时深挖",
        "category": "analysis",
        "trigger": "管理层研究/管理层评估/买股票就是买人/高管分析/人怎么样",
        "data": [
            ("管理层新闻/言论/事件", "`get_stock_news` + `web_search`"),
            ("业绩兑现核对（承诺 vs 交付）", "`get_financial_statements`（A股）/ `get_sec_filings`（美股）"),
            ("券商研报中的管理层观点", "`get_research_reports`"),
            ("股权/治理结构（美股/港股）", "`get_stock_profile`（institution/insider）"),
        ],
    },
    "private-company-research": {
        "purpose": "未上市公司深度研究",
        "scenario": "研究蚂蚁、SpaceX等信息稀缺的未上市公司",
        "category": "analysis",
        "trigger": "未上市公司研究/一级市场研究/私营公司/没上市的公司",
        "data": [
            ("未上市公司数据内置工具覆盖有限，仍以检索为主", "`web_search` + `read_url`（本 skill 原方式）"),
            ("可比上市同行财务/估值（用于对标）", "`get_stock_profile` / `get_financial_statements`"),
            ("同行行情", "`get_market_data`"),
        ],
    },
    "deep-company-series": {
        "purpose": "8篇长文系列拆一家公司",
        "scenario": "公众号级深度系列，12万字从认知重置到决策闭环",
        "category": "analysis",
        "trigger": "深度系列/系列长文/看懂XX/公众号深度文章",
        "data": [
            ("近 5 年年报 + 最新季报", "`get_financial_statements`（A股/港股）/ `get_sec_filings`（美股）"),
            ("卖方研报与一致预期", "`get_research_reports`（A股）"),
            ("新闻/公告流", "`get_stock_news`"),
            ("估值与市场cap校验", "`financial_rigor`（verify_valuation / verify_market_cap）"),
            ("US/HK 基本面速览", "`get_stock_profile`"),
        ],
    },
    # ── 财报分析类 ───────────────────────────────────────────────────────
    "earnings-review": {
        "purpose": "财报精读（一手资料）",
        "scenario": "只读原始财报，不依赖二手研报，像巴菲特一样读年报",
        "category": "analysis",
        "trigger": "财报精读/读财报/年报解读/季报解读/业绩分析",
        "data": [
            ("A股财报三大表+指标", "`get_financial_statements`（statement=income/balance/cashflow/indicators）"),
            ("美股 10-K/10-Q 与 XBRL 指标", "`get_sec_filings`"),
            ("原始财报 PDF（巨潮/EDGAR）", "`read_url` 下载后 `read_document` 解析"),
            ("港股财报", "`get_financial_statements`（东财源）/ `read_url`（披露易）"),
            ("数字交叉验证与精确计算", "`financial_rigor`（cross_validate / calc / benford）"),
        ],
    },
    "earnings-team": {
        "purpose": "财报精读团队 + 公众号发布",
        "scenario": "四大师并行解读财报 → 编辑润色 → 读者评审 → 可发布文章",
        "category": "analysis",
        "trigger": "财报团队/财报多人解读/财报公众号文章",
        "data": [
            ("A股财报三大表+指标", "`get_financial_statements`"),
            ("美股 10-K/10-Q 与 XBRL 指标", "`get_sec_filings`"),
            ("原始财报 PDF", "`read_url` + `read_document`"),
            ("数字交叉验证", "`financial_rigor`（cross_validate / benford）"),
            ("注意：并行 Agent 取数时同样遵守本节优先级", ""),
        ],
    },
    # ── 行业筛选类 ───────────────────────────────────────────────────────
    "industry-research": {
        "purpose": "产业链全景扫描",
        "scenario": "研究一个行业的全部投资机会（按产业链环节切片）",
        "category": "analysis",
        "trigger": "行业研究/产业链/全景扫描/这个行业有哪些机会",
        "data": [
            ("A股板块构成/今日热度", "`get_sector_info`（mode=membership / ranking）"),
            ("行业内公司清单与筛选", "`iwencai_search`（问财语义筛选）/ `screen_market`"),
            ("各环节公司财务对比", "`get_financial_statements`"),
            ("环节行情走势", "`get_market_data`"),
            ("行业研报与盈利预测", "`get_research_reports`"),
            ("产业链新闻/事件", "`get_stock_news`（scope=global）+ `web_search`"),
        ],
    },
    "industry-funnel": {
        "purpose": "行业漏斗筛选",
        "scenario": "全市场 → 粗筛 ≤10 家 → 终选 3 家深度分析",
        "category": "analysis",
        "trigger": "行业漏斗/漏斗筛选/行业里选几家/行业精选",
        "data": [
            ("行业公司清单初筛", "`iwencai_search` / `screen_market`"),
            ("粗筛指标（ROE/毛利/负债等）", "`get_financial_statements`（statement=indicators）"),
            ("US/HK 指标", "`get_stock_profile`（key_stats）"),
            ("估值闸门计算", "`financial_rigor`（calc / verify_valuation）"),
            ("行情与新闻", "`get_market_data` / `get_stock_news`"),
        ],
    },
    "quality-screen": {
        "purpose": "去劣筛选（7条硬指标）",
        "scenario": "快速排除非一流公司，支持个股/行业/指数/主题批量筛",
        "category": "analysis",
        "trigger": "去劣筛选/质量筛选/排除差公司/7条指标/批量筛选",
        "data": [
            ("A股批量指标筛选", "`iwencai_search`（如“ROE>15 连续5年 毛利率>30 资产负债率<50”）"),
            ("逐家财务指标", "`get_financial_statements`（statement=indicators）"),
            ("US/HK 关键指标", "`get_stock_profile`（key_stats）"),
            ("指标计算与交叉验证", "`financial_rigor`（cross_validate / calc）"),
        ],
    },
    "bottleneck-hunter": {
        "purpose": "供应链瓶颈猎手",
        "scenario": "从超级趋势出发，寻找产业链物理瓶颈和套利机会",
        "category": "analysis",
        "trigger": "供应链瓶颈/瓶颈猎手/卡脖子环节/产业链套利",
        "data": [
            ("瓶颈/扩产/断供新闻——工具覆盖弱，仍以检索为主", "`web_search` + `read_url`（本 skill 原方式）"),
            ("环节内上市公司清单", "`screen_market` / `iwencai_search`"),
            ("候选公司财务与产能", "`get_financial_statements`"),
            ("公司新闻", "`get_stock_news`"),
            ("估值闸门（PS/PE/安全边际）", "`financial_rigor`（calc / verify_valuation）"),
        ],
    },
    "era-alpha": {
        "purpose": "时代α捕手",
        "scenario": "识别时代级高增长主线中的核心α，验证增长可持续性，给出介入与退出纪律",
        "category": "analysis",
        "trigger": "时代阿尔法/时代alpha/高增长主线/核心资产识别",
        "data": [
            ("市场热度榜单（涨幅/成交额）", "`screen_market`（sort_by=change_pct / amount / turnover）"),
            ("板块/概念热度", "`get_sector_info`（mode=ranking）"),
            ("主线公司筛选", "`iwencai_search`"),
            ("增长验证（收入/利润增速）", "`get_financial_statements`（statement=indicators）"),
            ("动量与行情", "`get_market_data`"),
            ("新闻/事件", "`get_stock_news`"),
        ],
    },
    "investment-checklist": {
        "purpose": "巴菲特买入前 Checklist",
        "scenario": "六关快速筛选，10分钟决定是否值得深入",
        "category": "analysis",
        "trigger": "买入前检查/checklist/巴菲特清单/值不值得买",
        "data": [
            ("六关所需财务数据", "`get_financial_statements`（A股/港股）/ `get_sec_filings`（美股）"),
            ("US/HK 估值与关键指标", "`get_stock_profile`（key_stats）"),
            ("能力圈/生意模式判断所需新闻", "`get_stock_news` + `web_search`"),
            ("ROE/负债率等计算", "`financial_rigor`（calc）"),
        ],
    },
    # ── 持仓管理类 ───────────────────────────────────────────────────────
    "income-investment": {
        "purpose": "收益型股票分析",
        "scenario": "区分可持续收益、机会型高息与收益率陷阱",
        "category": "strategy",
        "trigger": "收息股/高股息/红利策略/股息率分析/收益型",
        "data": [
            ("股息率/派息记录（US/HK）", "`get_stock_profile`（key_stats / financials）"),
            ("分红与现金流核验", "`get_financial_statements`（cashflow / income）"),
            ("价格与收益率计算", "`get_market_data` + `financial_rigor`（calc）"),
        ],
    },
    "portfolio-review": {
        "purpose": "组合管理与优化",
        "scenario": "从“研究公司”升级到“管理组合”——仓位、集中度、再平衡",
        "category": "strategy",
        "trigger": "组合复盘/仓位管理/再平衡/持仓优化/集中度",
        "data": [
            ("持仓最新行情", "`get_market_data`"),
            ("持仓基本面复核", "`get_financial_statements` / `get_stock_profile`"),
            ("A股风险事件（解禁/资金流）", "`get_lockup_expiry` / `get_fund_flow`"),
            ("持仓新闻", "`get_stock_news`"),
            ("组合数学（权重/相关/集中度）", "`financial_rigor`（calc）"),
        ],
    },
    "thesis-tracker": {
        "purpose": "投资论文追踪",
        "scenario": "买入后的纪律系统：持续跟踪论文是否被证伪",
        "category": "strategy",
        "trigger": "投资论文/论文追踪/买入理由复查/论点被证伪/季度复核",
        "data": [
            ("最新财报（对照论点）", "`get_financial_statements` / `get_sec_filings`"),
            ("最新新闻/公告", "`get_stock_news`"),
            ("研报预期变化", "`get_research_reports`"),
            ("当前价格与估值锚", "`get_market_data` + `financial_rigor`（verify_valuation）"),
        ],
    },
    "thesis-drift": {
        "purpose": "投资论文漂移检测",
        "scenario": "对比两份论文/报告，区分事实变化、估值变化与措辞变化",
        "category": "strategy",
        "trigger": "论文漂移/观点变化对比/报告对比/措辞变化",
        "data": [
            ("两份报告原文（本地文件/PDF）", "`read_file` / `read_document`"),
            ("争议事实的最新核对", "`get_financial_statements` / `get_stock_news` / `web_search`"),
        ],
    },
    "news-pulse": {
        "purpose": "股价异动快速归因",
        "scenario": "股价大涨/大跌时10分钟搞清“发生了什么”",
        "category": "flow",
        "trigger": "股价异动/为什么涨/为什么跌/新闻脉搏/异动归因/发生了什么",
        "data": [
            ("公司新闻快线", "`get_stock_news`"),
            ("主力资金流", "`get_fund_flow`（daily / min）"),
            ("龙虎榜/大宗交易", "`get_dragon_tiger` / `get_block_trades`"),
            ("融资融券余额变化", "`get_margin_trading`"),
            ("解禁/股东户数", "`get_lockup_expiry` / `get_shareholder_count`"),
            ("监管/行业级事件兜底", "`web_search`（本 skill 原方式）"),
        ],
    },
    # ── 思维工具类 ───────────────────────────────────────────────────────
    "dyp-ask": {"purpose": "段永平问答", "scenario": "以段永平的方式思考任何问题——商业、投资、人生", "category": "tool", "trigger": "段永平/大道怎么想/大道怎么看", "data": None},
    "financial-data": {"purpose": "财务数据获取与交叉验证规范", "scenario": "确保关键数据来自2个独立来源，误差>1%告警", "category": "tool", "trigger": "财务数据规范/数据交叉验证/数据口径/两个来源", "data": "SPECIAL"},
    "wechat-article": {"purpose": "微信公众号文章", "scenario": "作者、编辑、读者三Agent协作，产出可发布文章", "category": "tool", "trigger": "公众号文章/微信文章/写成文章发布", "data": None},
}

# financial-data IS the data-layer spec: rewrite its source-priority guidance
# for the TradingClaw runtime instead of the generic table.
FINANCIAL_DATA_BLOCK = """\
> **⚡ TradingClaw 数据加速层**（本环境内置数据工具，是“更快更稳定的一手来源”；下列来源不可用或需要网页/PDF 原文时，才回退到本 skill 原始的网页访问方式）：
>
> | 市场 | 主来源（内置工具） | 副来源（交叉验证） |
> |---|---|---|
> | A股 | `get_financial_statements`（新浪源，income/balance/cashflow/indicators，annual/quarter） | `read_url`（东方财富/巨潮 PDF）+ `read_document` |
> | 美股 | `get_sec_filings`（SEC EDGAR 原文 + XBRL 指标） | `get_stock_profile` / `read_url` |
> | 港股 | `get_financial_statements`（东财源） | `read_url`（披露易）+ `read_document` |
> | 行情（前复权统一口径） | `get_market_data`（adjust=qfq，A股/港股/美股/加密） | `web_search` |
> | 代码/名称解析 | `search_symbol` | `web_search` |
>
> 交叉验证与精确计算：`financial_rigor`（cross_validate / calc / verify_valuation / verify_market_cap / benford，Decimal 精确十进制）。两个来源误差 > 1% 的告警规则照旧执行。"""

OUTPUT_RULE = (
    "> **报告输出**：全文 Markdown 存入文件，同时把**完整报告直接作为最终回复**输出——"
    "飞书渠道会自动渲染为卡片、超限自动分片；不要只回一个本地文件路径。"
)

# financial-data's block ends with the same output rule as the generic block.
FINANCIAL_DATA_BLOCK = FINANCIAL_DATA_BLOCK + "\n>\n" + OUTPUT_RULE


def _data_block(rows: list[tuple[str, str]]) -> str:
    lines = [
        "> **⚡ TradingClaw 数据加速层**（本环境内置数据工具，直连数据源、比网页抓取更快更稳。"
        "下文任何“搜索/抓取/获取数据”的指令，**先走下表工具**；工具不可用、字段缺失或需要网页/PDF 原文时，"
        "再回退到本 skill 原始方式 `web_search` / `read_url`）：",
        ">",
        "> | 数据需求 | 首选工具 |",
        "> |---|---|",
    ]
    for need, tool in rows:
        lines.append(f"> | {need} | {tool} |")
    lines.append(">")
    lines.append(OUTPUT_RULE)
    return "\n".join(lines)


def _strip_upstream_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return text


def build_skill(name: str, meta: dict, source_dir: Path) -> None:
    src = source_dir / "skills" / f"{name}.md"
    if not src.exists():
        raise FileNotFoundError(f"upstream skill missing: {src}")
    body = _strip_upstream_frontmatter(src.read_text(encoding="utf-8"))

    purpose, scenario = meta["purpose"], meta["scenario"]
    desc = (
        f"AI Berkshire skill: {purpose}——{scenario}。"
        f"触发词：{meta['trigger']}、{name}。"
    )

    parts = [f"---\nname: {name}\ncategory: {meta['category']}\ndescription: \"{desc}\"\n---\n"]

    # Insert the data layer right after the H1 title line so the tool table is
    # the first thing the agent reads; fall back to the very top if no H1.
    h1_match = re.search(r"^# .*$", body, re.MULTILINE)
    if meta.get("data") is None:
        parts.append(body)
    else:
        block = FINANCIAL_DATA_BLOCK if meta["data"] == "SPECIAL" else _data_block(meta["data"])
        if h1_match:
            end = h1_match.end()
            parts.append(body[:end] + "\n\n" + block + "\n\n---" + body[end:])
        else:
            parts.append(block + "\n\n---\n\n" + body)

    out_dir = OUT_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "SKILL.md").write_text("".join(parts), encoding="utf-8")
    print(f"  built {name}")


def ensure_source(path: Path) -> Path:
    if (path / "skills").is_dir():
        subprocess.run(["git", "-C", str(path), "pull", "--ff-only"], check=False, capture_output=True)
        return path
    if path == DEFAULT_SOURCE:
        print(f"cloning upstream → {path}")
        subprocess.run(["git", "clone", "--depth", "1", UPSTREAM_URL, str(path)], check=True)
        return path
    raise FileNotFoundError(f"--source {path} does not look like an ai-berkshire checkout")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                    help="existing ai-berkshire checkout (default: clone to /tmp/ai-berkshire)")
    args = ap.parse_args()

    source = ensure_source(args.source)
    print(f"building {len(SKILLS)} berkshire skills → {OUT_DIR}")
    for name, meta in SKILLS.items():
        build_skill(name, meta, source)
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
