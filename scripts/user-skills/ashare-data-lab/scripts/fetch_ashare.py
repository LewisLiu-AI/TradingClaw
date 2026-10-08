#!/usr/bin/env python3
"""A股研究数据采集器 —— 一个标的的全部可用数据, 一次抓齐。

用法:
    python fetch_ashare.py --symbol 301526.SZ --outdir ./data [--start 2024-06-01] [--end 2026-09-12]
    python fetch_ashare.py --symbol 600519.SH --outdir ./data --only prices,margin
    python fetch_ashare.py --global-macro --outdir ./data          # 只要跨资产
    python fetch_ashare.py --northbound --start 2026-09-01 --end 2026-09-12 --outdir ./data

设计要点(每一条都是实测踩坑后的结论, 详见 references/pitfalls.md):
  * 东财 push2his 经本地代理会间歇性 ProxyError —— 每个端点都要重试 + 备用源(新浪)兜底。
  * akshare 部分东财接口在密集请求下会断连 —— 统一节流。
  * 深市两融在全市场口径下缺 177 个交易日(2024-06~2025-06), 所以沪市单边单独保存。
  * 北向资金**净买入自 2024-08-19 起停止披露**, 现在只有 HKEX 的成交额(Total Turnover)。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
EM_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EM_DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HKEX = "https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_{code}e.js"
KCOLS = ["date", "open", "close", "high", "low", "volume", "amount",
         "amplitude", "pct_chg", "change", "turnover"]


def log(m: str) -> None:
    print(f"[fetch] {m}", flush=True)


def get_json(url: str, params: dict, tries: int = 5, sleep: float = 2.0) -> dict | None:
    """带退避重试的 GET(本地代理会间歇性断连, 必须重试)。"""
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=25, headers=UA)
            if r.status_code == 200:
                return r.json()
        except Exception as exc:  # noqa: BLE001
            if i == tries - 1:
                log(f"  放弃 {url.split('?')[0].split('/')[-1]}: {type(exc).__name__}")
        time.sleep(sleep * (i + 1))
    return None


def save(df: pd.DataFrame | None, out: Path, name: str) -> None:
    if df is None or len(df) == 0:
        log(f"{name}: 空")
        return
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / f"{name}.csv", encoding="utf-8-sig")
    rng = ""
    if isinstance(df.index, pd.DatetimeIndex) and len(df):
        rng = f" {df.index.min().date()}~{df.index.max().date()}"
    log(f"{name}: {len(df)} 行{rng}")


def to_numeric_cols(df: pd.DataFrame, skip: tuple = ("buyer", "seller", "name", "title",
                                                     "type", "reason", "source", "url")) -> pd.DataFrame:
    """只对数值列做 to_numeric。

    ⚠️ 对文本列(如大宗交易的买卖席位)做 to_numeric 会**静默变成全 NaN** —— 实测踩过。
    """
    for c in df.columns:
        if str(c).lower() in skip or str(c).lower().startswith(("unnamed", "index")):
            continue
        if df[c].dtype == object:
            conv = pd.to_numeric(df[c], errors="coerce")
            if conv.notna().sum() >= max(1, int(0.5 * df[c].notna().sum())):
                df[c] = conv
    return df


def norm_turnover(df: pd.DataFrame) -> pd.DataFrame:
    """把换手率统一为**百分数**。

    各源口径不一致(新浪是小数 0.0433 = 4.33%, 东财是百分数) ——
    与来源无关的做法是"先看量级再决定是否 ×100", 而不是硬编码乘数(硬编码会制造污染)。
    """
    if "turnover" in df.columns:
        v = pd.to_numeric(df["turnover"], errors="coerce")
        if v.max() < 1.5:
            v = v * 100
            log("  turnover: 判定为小数口径, 已 ×100 归一为百分数")
        df["turnover"] = v
    return df


def secid(symbol: str) -> str:
    code, _, mkt = symbol.partition(".")
    return ("1." if mkt.upper() in ("SH", "SS") else "0.") + code


def sina_symbol(symbol: str) -> str:
    code, _, mkt = symbol.partition(".")
    return ("sh" if mkt.upper() in ("SH", "SS") else "sz") + code


# ───────────────────────── 行情(三口径) ─────────────────────────
def fetch_prices(symbol: str, start: str, end: str, out: Path) -> None:
    beg, fin = start.replace("-", ""), end.replace("-", "")
    for fqt, name in ((2, "px_raw"), (1, "px_qfq"), (0, "px_hfq")):
        df = None
        j = get_json(EM_KLINE, {"secid": secid(symbol), "fields1": "f1,f2,f3,f4,f5,f6",
                                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                                "klt": 101, "fqt": fqt, "beg": beg, "end": fin,
                                "ut": "fa5fd1943c7b386f172d6893dbfba10b"})
        kl = (j or {}).get("data", {}).get("klines") if j else None
        if kl:
            df = pd.DataFrame([dict(zip(KCOLS, k.split(","))) for k in kl])
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            df = to_numeric_cols(df)
        else:
            # 兜底: 新浪(注意 turnover 是**小数**口径, 校验器会告警)
            try:
                import akshare as ak
                raw = ak.stock_zh_a_daily(symbol=sina_symbol(symbol),
                                          start_date=beg, end_date=fin,
                                          adjust={2: "", 1: "qfq", 0: "hfq"}[fqt])
                raw = raw.reset_index() if raw.index.name == "date" else raw
                raw["date"] = pd.to_datetime(raw["date"])
                df = raw.set_index("date")
                log(f"  {name}: 东财失败, 用新浪兜底")
            except Exception as exc:  # noqa: BLE001
                log(f"  {name}: 两源都失败 {type(exc).__name__}")
        if df is not None:
            df = norm_turnover(to_numeric_cols(df))
        save(df, out, name)
        time.sleep(1.2)


def fetch_index(symbols: dict, start: str, end: str, out: Path) -> None:
    beg, fin = start.replace("-", ""), end.replace("-", "")
    for name, sid in symbols.items():
        df = None
        j = get_json(EM_KLINE, {"secid": sid, "fields1": "f1,f2,f3,f4,f5,f6",
                                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                                "klt": 101, "fqt": 1, "beg": beg, "end": fin,
                                "ut": "fa5fd1943c7b386f172d6893dbfba10b"})
        kl = (j or {}).get("data", {}).get("klines") if j else None
        if kl:
            df = pd.DataFrame([dict(zip(KCOLS, k.split(","))) for k in kl])
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            for c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
        save(df, out, name)
        time.sleep(1.2)


# ───────────────────────── 个股两融(硬数据) ─────────────────────────
def fetch_margin(symbol: str, out: Path) -> None:
    code = symbol.split(".")[0]
    rows, page = [], 1
    while page <= 5:
        j = get_json(EM_DC, {"reportName": "RPTA_WEB_RZRQ_GGMX", "columns": "ALL",
                             "filter": f'(scode="{code}")', "pageNumber": page,
                             "pageSize": 500, "sortColumns": "DATE", "sortTypes": 1,
                             "source": "WEB", "client": "WEB"})
        data = ((j or {}).get("result") or {}).get("data") or []
        if not data:
            break
        rows += data
        if len(data) < 500:
            break
        page += 1
        time.sleep(1.0)
    if not rows:
        log("margin: 空")
        return
    d = pd.DataFrame(rows).rename(columns={
        "DATE": "date", "RZYE": "rz_balance", "RZMRE": "rz_buy", "RZCHE": "rz_repay",
        "RZJME": "rz_net", "RQYE": "rq_balance", "RQYL": "rq_volume",
        "RZRQYE": "rzrq_balance", "RZYEZB": "rz_balance_pct_float",
        "SZ": "float_mktcap", "SPJ": "close", "ZDF": "pct_chg"})
    keep = ["date", "close", "pct_chg", "rz_balance", "rz_buy", "rz_repay", "rz_net",
            "rz_balance_pct_float", "rq_balance", "rq_volume", "rzrq_balance", "float_mktcap"]
    d = d[[c for c in keep if c in d.columns]]
    d["date"] = pd.to_datetime(d["date"])
    d = to_numeric_cols(d)
    save(d.set_index("date"), out, "margin")


# ───────────────────────── 市场级两融(注意缺口) ─────────────────────────
def fetch_market_margin(out: Path) -> None:
    try:
        import akshare as ak
    except ImportError:
        log("akshare 未安装, 跳过 market margin")
        return
    legs = {}
    for fn, tag in ((ak.macro_china_market_margin_sz, "sz"),
                    (ak.macro_china_market_margin_sh, "sh")):
        try:
            d = fn()
            d["日期"] = pd.to_datetime(d["日期"])
            d = d.set_index("日期").sort_index()
            legs[tag] = d[["融资余额"]]
            log(f"  market_margin_{tag}: {len(d)} 行, 非空 {int(d['融资余额'].notna().sum())}")
        except Exception as exc:  # noqa: BLE001
            log(f"  market_margin_{tag} 失败 {type(exc).__name__}")
        time.sleep(1.0)
    if "sh" not in legs:
        return
    m = (legs["sh"] / 1e8).rename(columns={"融资余额": "mkt_rz_balance_sh"})
    if "sz" in legs:
        m["mkt_rz_balance_total"] = (legs["sh"]["融资余额"] + legs["sz"]["融资余额"]) / 1e8
    else:
        m["mkt_rz_balance_total"] = np.nan
    m.index.name = "date"
    save(m, out, "mkt_margin")
    n_bad = int(m["mkt_rz_balance_total"].isna().sum())
    if n_bad:
        log(f"  ⚠️ 两市合计缺 {n_bad}/{len(m)} 天 —— **分析请用 mkt_rz_balance_sh(沪市单边, 完整)**")


# ───────────────────────── 事件面 ─────────────────────────
def fetch_block_trade(symbol: str, out: Path) -> None:
    code = symbol.split(".")[0]
    j = get_json(EM_DC, {"reportName": "RPT_DATA_BLOCKTRADE", "columns": "ALL",
                         "filter": f'(SECURITY_CODE="{code}")', "pageNumber": 1,
                         "pageSize": 500, "sortColumns": "TRADE_DATE", "sortTypes": 1,
                         "source": "WEB", "client": "WEB"})
    data = ((j or {}).get("result") or {}).get("data") or []
    if not data:
        log("block_trade: 空")
        return
    d = pd.DataFrame(data).rename(columns={
        "TRADE_DATE": "date", "DEAL_PRICE": "price", "CLOSE_PRICE": "close",
        "PREMIUM_RATIO": "premium_pct", "DEAL_VOLUME": "volume", "DEAL_AMT": "amount",
        "BUYER_NAME": "buyer", "SELLER_NAME": "seller"})
    keep = [c for c in ["date", "price", "close", "premium_pct", "volume", "amount",
                        "buyer", "seller"] if c in d.columns]
    d = d[keep]
    d["date"] = pd.to_datetime(d["date"])
    d = to_numeric_cols(d)                        # buyer/seller 是文本, 不可转数值
    if "premium_pct" in d.columns:
        d["premium_pct"] = d["premium_pct"] * 100  # 折溢率 -> %
    save(d.set_index("date"), out, "block_trade")


def fetch_announcements(symbol: str, out: Path) -> None:
    code = symbol.split(".")[0]
    rows = []
    for page in range(1, 5):
        j = get_json("https://np-anotice-stock.eastmoney.com/api/security/ann",
                     {"sr": -1, "page_size": 50, "page_index": page, "ann_type": "A",
                      "client_source": "web", "stock_list": code})
        data = ((j or {}).get("data") or {}).get("list") or []
        if not data:
            break
        for it in data:
            rows.append({"date": str(it.get("notice_date", ""))[:10],
                         "title": it.get("title", ""),
                         "type": ",".join(c.get("column_name", "") for c in (it.get("columns") or []))})
        time.sleep(1.0)
    if not rows:
        log("announcements: 空")
        return
    d = pd.DataFrame(rows).drop_duplicates(subset=["date", "title"])
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["date"]).sort_values("date", ascending=False)
    out.mkdir(parents=True, exist_ok=True)
    d.to_csv(out / "announcements.csv", index=False, encoding="utf-8-sig")
    log(f"announcements: {len(d)} 行")


# ───────────────────────── 跨资产(yfinance) ─────────────────────────
CROSS = {"GC=F": "gold", "CL=F": "oil", "^TNX": "us10y", "DX-Y.NYB": "dxy", "^VIX": "vix",
         "^SOX": "sox", "^IXIC": "ixic", "HG=F": "copper", "^HSI": "hsi"}
# 注: 没有 ^HSTECH(雅虎无此代码); 人民币汇率可用 USDCNH=X


def fetch_global(start: str, end: str, out: Path) -> None:
    try:
        import yfinance as yf
    except ImportError:
        log("yfinance 未安装, 跳过跨资产")
        return
    gdir = out / "global"
    gdir.mkdir(parents=True, exist_ok=True)
    for sym, tag in CROSS.items():
        try:
            raw = yf.download(sym, start=start, end=end, progress=False, auto_adjust=True)
            c = raw["Close"].dropna()
            c = c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c
            c.index.name = "date"
            c.to_frame("close").to_csv(gdir / f"{tag}.csv", encoding="utf-8-sig")
            log(f"global/{tag}: {len(c)} 行")
        except Exception as exc:  # noqa: BLE001
            log(f"global/{tag} 失败 {type(exc).__name__}")
        time.sleep(0.5)


# ───────────────────────── 北向成交额(HKEX 官方) ─────────────────────────
def fetch_northbound(start: str, end: str, out: Path) -> None:
    """北向**成交额**(不是净买入 —— 净买入自 2024-08-19 起停止披露)。

    HKEX 日度统计只有 Total Turnover / Buy/Sell Turnover: 北向连买卖拆分都没有,
    南向才有。个股层面是"成交额排行", 同样只有 Total Turnover。
    """
    rows = []
    for dt in pd.bdate_range(start, end):
        j = get_json(HKEX.format(code=dt.strftime("%Y%m%d")), {}, tries=2, sleep=1.0)
        if not j:
            continue
        # payload 形如 {"tabData": [...]} 或裸 list
        payload = j.get("tabData") if isinstance(j, dict) else j
        if not isinstance(payload, list):
            continue
        rec = {"date": dt}
        for e in payload:
            mkt = str((e or {}).get("market") or "")
            content = (e or {}).get("content") or []
            if not mkt or not content:
                continue
            table = (content[0] or {}).get("table") or {}
            sch = (table.get("schema") or [[]])[0]
            tr = (table.get("tr") or [{}])[0]
            td = (tr or {}).get("td") or [[]]
            vals = [x[0] if isinstance(x, list) and x else x for x in td]
            by = dict(zip(sch, vals))
            if "Turnover" in by:
                rec[mkt.replace(" ", "_")] = float(str(by["Total Turnover"]).replace(",", ""))
        if len(rec) > 1:
            rows.append(rec)
        time.sleep(0.8)
    if not rows:
        log("northbound: 空 (HKEX 当日无数据或已休市)")
        return
    d = pd.DataFrame(rows).set_index("date")
    d["northbound_total_turnover_mn"] = (d.get("SSE_Northbound", 0) + d.get("SZSE_Northbound", 0))
    save(d, out, "northbound_turnover")
    log("单位: 百万人民币(HKEX 口径); 北向只有成交额, 无净买入")


STEPS = {
    "prices": lambda a: fetch_prices(a.symbol, a.start, a.end, Path(a.outdir)),
    "index": lambda a: fetch_index({"idx_cyb": "0.399006", "idx_hs300": "1.000300",
                                    "idx_zz500": "1.000905", "idx_cyb50": "0.399295",
                                    "mkt_sse": "1.000001", "mkt_szse": "0.399001",
                                    "mkt_csi500": "1.000905", "mkt_sse50": "1.000016"},
                                   a.start, a.end, Path(a.outdir)),
    "margin": lambda a: fetch_margin(a.symbol, Path(a.outdir)),
    "market_margin": lambda a: fetch_market_margin(Path(a.outdir)),
    "block": lambda a: fetch_block_trade(a.symbol, Path(a.outdir)),
    "ann": lambda a: fetch_announcements(a.symbol, Path(a.outdir)),
    "global": lambda a: fetch_global(a.start, a.end, Path(a.outdir)),
    "northbound": lambda a: fetch_northbound(a.start, a.end, Path(a.outdir)),
}


def main() -> None:
    ap = argparse.ArgumentParser(description="A股研究数据采集器")
    ap.add_argument("--symbol", default="301526.SZ")
    ap.add_argument("--outdir", default="./data")
    ap.add_argument("--start", default="2024-06-01")
    ap.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    ap.add_argument("--only", default="", help="逗号分隔: " + ",".join(STEPS))
    ap.add_argument("--global-macro", action="store_true", help="只抓跨资产")
    ap.add_argument("--northbound", action="store_true", help="只抓北向成交额")
    args = ap.parse_args()

    if args.global_macro:
        fetch_global(args.start, args.end, Path(args.outdir))
        return
    if args.northbound:
        fetch_northbound(args.start, args.end, Path(args.outdir))
        return

    steps = [s.strip() for s in args.only.split(",") if s.strip()] or (
        ["prices", "index", "margin", "market_margin", "block", "ann"])
    log(f"symbol={args.symbol} window={args.start}..{args.end} -> {args.outdir}")
    for s in steps:
        if s not in STEPS:
            log(f"未知步骤 {s}")
            continue
        log(f"--- {s} ---")
        STEPS[s](args)
    # 清单
    p = Path(args.outdir)
    man = {"symbol": args.symbol, "start": args.start, "end": args.end,
           "files": sorted(f.name for f in p.glob("*.csv"))}
    (p / "_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2))
    log(f"完成, {len(man['files'])} 个 CSV。**下一步: python validate_data.py {args.outdir}**")


if __name__ == "__main__":
    main()
