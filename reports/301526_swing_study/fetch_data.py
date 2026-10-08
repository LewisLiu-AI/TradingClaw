#!/usr/bin/env python
"""国际复材(301526.SZ) 波段策略研究 — 数据抓取

统一落盘到 data/，字段名统一为英文，index 为 trade_date。
数据源:
  - akshare (东财/新浪)  : 行情、资金流、龙虎榜、大宗、股东户数、解禁、新闻、指数
  - 东财 datacenter 直连 : 个股融资融券明细(全历史)

用法: python fetch_data.py [--start 2024-06-01] [--end 2026-09-12]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import akshare as ak
import pandas as pd
import requests

CODE = "301526"
SYMBOL = "301526.SZ"
SECID = "0.301526"  # 0=深市
OUT = Path(__file__).parent / "data"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def log(msg: str) -> None:
    print(f"[fetch] {msg}", flush=True)


def retry(fn, *a, tries: int = 4, sleep: float = 2.5, **kw):
    last = None
    for i in range(tries):
        try:
            return fn(*a, **kw)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(sleep * (i + 1))
    log(f"FAIL {getattr(fn, '__name__', fn)}: {type(last).__name__}: {last}")
    return None


def throttle(seconds: float = 1.2) -> None:
    """本地代理(127.0.0.1:7890)在密集请求下会断连，统一节流。"""
    time.sleep(seconds)


def save(df: pd.DataFrame, name: str, date_col: str = "date") -> None:
    if df is None or len(df) == 0:
        log(f"{name}: empty, skipped")
        return
    df = df.copy()
    if date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.sort_values(date_col).drop_duplicates(subset=[date_col], keep="last")
        df = df.set_index(date_col)
    df.to_csv(OUT / f"{name}.csv", encoding="utf-8-sig")
    log(f"{name}: {len(df)} rows -> data/{name}.csv  ({df.index.min()} .. {df.index.max()})")


# ────────────────────────────── 行情 ──────────────────────────────


KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
KLINE_F2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
KLINE_COLS = ["date", "open", "close", "high", "low", "volume", "amount",
              "amplitude", "pct_chg", "change", "turnover"]


def _em_kline(secid: str, beg: str, end: str, fqt: int) -> pd.DataFrame | None:
    """直连东财 K 线（akshare 同源，但绕开其不稳定的重试策略）。"""
    params = {"secid": secid, "fields1": "f1,f2,f3,f4,f5,f6", "fields2": KLINE_F2,
              "klt": 101, "fqt": fqt, "beg": beg, "end": end,
              "ut": "fa5fd1943c7b386f172d6893dbfba10b"}
    for i in range(5):
        try:
            j = requests.get(KLINE_URL, params=params, timeout=20, headers=UA).json()
            kl = (j.get("data") or {}).get("klines")
            if kl:
                rows = [dict(zip(KLINE_COLS, k.split(","))) for k in kl]
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                for c in df.columns[1:]:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                return df
        except Exception as exc:  # noqa: BLE001
            log(f"  em_kline retry {i + 1}: {type(exc).__name__}")
        time.sleep(2.0 * (i + 1))
    return None


def _sina_daily(adjust: str, start: str, end: str) -> pd.DataFrame | None:
    df = retry(ak.stock_zh_a_daily, symbol=f"sz{CODE}",
               start_date=start.replace("-", ""), end_date=end.replace("-", ""),
               adjust=adjust)
    if df is None or len(df) == 0:
        return None
    df = df.reset_index() if df.index.name == "date" else df
    df["date"] = pd.to_datetime(df["date"])
    return df


def fetch_prices(start: str, end: str) -> None:
    s, e = start.replace("-", ""), end.replace("-", "")
    for fqt, adjust, name in ((2, "", "px_raw"), (1, "qfq", "px_qfq"), (0, "hfq", "px_hfq")):
        df = _em_kline(SECID, s, e, fqt)
        if df is None:
            log(f"{name}: EM failed, fallback to sina ({adjust or 'raw'})")
            df = _sina_daily(adjust, start, end)
        if df is None:
            log(f"{name}: FAILED (both sources)")
            continue
        keep = ["date", "open", "high", "low", "close", "volume", "amount",
                "pct_chg", "turnover", "amplitude"]
        df = df[[c for c in keep if c in df.columns]]
        if "turnover" not in df.columns and "outstanding_share" in df.columns:
            df["turnover"] = df["volume"] / df["outstanding_share"] * 100
        save(df, name)
        throttle()


def fetch_index(start: str, end: str) -> None:
    """创业板指 / 沪深300 / 中证500 / 创业板50 — beta 与相对强度基准。"""
    s, e = start.replace("-", ""), end.replace("-", "")
    for secid, sym, name in (("0.399006", "sz399006", "idx_cyb"),
                             ("1.000300", "sh000300", "idx_hs300"),
                             ("1.000905", "sh000905", "idx_zz500"),
                             ("0.399295", "sz399295", "idx_cyb50")):
        df = _em_kline(secid, s, e, 1)
        if df is None:
            df = retry(ak.stock_zh_index_daily, symbol=sym)
            if df is not None:
                df = (df.reset_index() if df.index.name == "date" else df)
                df["date"] = pd.to_datetime(df["date"])
                df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
        if df is None:
            log(f"{name}: FAILED")
            continue
        keep = ["date", "open", "high", "low", "close", "volume", "amount", "pct_chg"]
        save(df[[c for c in keep if c in df.columns]], name)
        throttle()



# ──────────────────────────── 资金 / 融资 ────────────────────────────


def fetch_moneyflow_full() -> None:
    """东财个股资金流全历史(主力/超大单/大单/中单/小单净额与净占比)。"""
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "lmt": 0, "klt": 101, "secid": SECID,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
    }
    try:
        j = requests.get(url, params=params, timeout=25, headers=UA).json()
        klines = (j.get("data") or {}).get("klines") or []
    except Exception as exc:  # noqa: BLE001
        log(f"moneyflow_full FAIL: {exc}")
        klines = []
    if klines:
        cols = ["date", "main_net", "small_net", "mid_net", "big_net", "super_net",
                "main_pct", "small_pct", "mid_pct", "big_pct", "super_pct",
                "close", "pct_chg", "x13", "x14"][: len(klines[0].split(","))]
        rows = [dict(zip(cols, k.split(","))) for k in klines]
        df = pd.DataFrame(rows)
        num = [c for c in df.columns if c != "date"]
        df[num] = df[num].apply(pd.to_numeric, errors="coerce")
        df = df[["date", "main_net", "main_pct", "super_net", "super_pct",
                 "big_net", "big_pct", "mid_net", "mid_pct", "small_net", "small_pct"]]
        for c in ("main_net", "super_net", "big_net", "mid_net", "small_net"):
            df[c] = df[c] / 1e4  # 元 -> 万元
        save(df, "moneyflow")
    # akshare 口径交叉校验(近120日)
    df2 = retry(ak.stock_individual_fund_flow, stock=CODE, market="sz")
    if df2 is not None:
        df2 = df2.rename(columns={"日期": "date", "收盘价": "close", "涨跌幅": "pct_chg",
                                  "主力净流入-净额": "main_net_em", "主力净流入-净占比": "main_pct_em"})
        save(df2[["date", "close", "pct_chg", "main_net_em", "main_pct_em"]], "moneyflow_em_xcheck")


def fetch_margin() -> None:
    """东财个股融资融券明细全历史。融资余额是硬数据(交易所披露)。"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    rows, page = [], 1
    while True:
        p = {"reportName": "RPTA_WEB_RZRQ_GGMX", "columns": "ALL",
             "filter": f'(scode="{CODE}")', "pageNumber": page, "pageSize": 500,
             "sortColumns": "DATE", "sortTypes": 1, "source": "WEB", "client": "WEB"}
        try:
            j = requests.get(url, params=p, timeout=25, headers=UA).json()
        except Exception as exc:  # noqa: BLE001
            log(f"margin FAIL page{page}: {exc}")
            break
        data = (j.get("result") or {}).get("data") or []
        if not data:
            break
        rows.extend(data)
        if len(data) < 500:
            break
        page += 1
    if not rows:
        return
    df = pd.DataFrame(rows)
    df = df.rename(columns={
        "DATE": "date", "RZYE": "rz_balance", "RZMRE": "rz_buy",
        "RZCHE": "rz_repay", "RZJME": "rz_net", "RQYE": "rq_balance",
        "RQYL": "rq_volume", "RQMCL": "rq_sell_vol", "RQCHL": "rq_repay_vol",
        "RZRQYE": "rzrq_balance", "RZYEZB": "rz_balance_pct_float",
        "SZ": "float_mktcap", "SPJ": "close", "ZDF": "pct_chg",
        "RZMRE3D": "rz_buy_3d", "RZMRE5D": "rz_buy_5d", "RZMRE10D": "rz_buy_10d",
        "RZJME3D": "rz_net_3d", "RZJME5D": "rz_net_5d", "RZJME10D": "rz_net_10d",
    })
    keep = ["date", "close", "pct_chg", "rz_balance", "rz_buy", "rz_repay", "rz_net",
            "rz_balance_pct_float", "rq_balance", "rq_volume", "rzrq_balance", "float_mktcap"]
    df = df[[c for c in keep if c in df.columns]]
    for c in df.columns:
        if c != "date":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    save(df, "margin")


# ──────────────────────────── 筹码 / 事件 ────────────────────────────


def fetch_holders() -> None:
    """股东户数（季度披露，筹码集中度）。"""
    df = retry(ak.stock_zh_a_gdhs_detail_em, symbol=CODE)
    if df is not None:
        df = df.rename(columns={"股东户数统计截止日": "date", "股东户数-本次": "holders",
                                "股东户数-上次": "holders_prev", "股东户数-增减": "holders_chg",
                                "股东户数-增减比例": "holders_chg_pct",
                                "户均持股市值": "avg_mktcap", "户均持股数量": "avg_shares",
                                "总市值": "total_mktcap", "总股本": "total_shares",
                                "股本变动": "share_change", "股本变动原因": "share_change_reason"})
        cols = [c for c in ["date", "holders", "holders_prev", "holders_chg",
                            "holders_chg_pct", "avg_mktcap", "avg_shares",
                            "total_mktcap", "total_shares"] if c in df.columns]
        save(df[cols], "holders")


def fetch_lhb(start: str, end: str) -> None:
    """龙虎榜明细（区间全市场，过滤本股）。"""
    s, e = start.replace("-", ""), end.replace("-", "")
    df = retry(ak.stock_lhb_detail_em, start_date=s, end_date=e)
    if df is None:
        return
    df = df.rename(columns={"序号": "seq", "代码": "code", "名称": "name", "上榜日": "date",
                            "解读": "reason", "收盘价": "close", "涨跌幅": "pct_chg",
                            "龙虎榜净买额": "lhb_net", "龙虎榜买入额": "lhb_buy",
                            "龙虎榜卖出额": "lhb_sell", "龙虎榜成交额": "lhb_amount",
                            "市场总成交额": "mkt_amount", "净买额占总成交比": "net_ratio",
                            "成交额占总成交比": "amount_ratio", "换手率": "turnover",
                            "流通市值": "float_mktcap", "上榜原因": "lhb_reason",
                            "上榜后1日": "fwd1", "上榜后2日": "fwd2",
                            "上榜后5日": "fwd5", "上榜后10日": "fwd10"})
    sub = df[df["code"].astype(str).str.zfill(6) == CODE]
    save(sub, "lhb")


def fetch_block_trade(start: str, end: str) -> None:
    """大宗交易（东财 datacenter 直连）— 折价率是机构/大股东减持信号。"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    rows, page = [], 1
    while page <= 5:
        p = {"reportName": "RPT_DATA_BLOCKTRADE", "columns": "ALL",
             "filter": f'(SECURITY_CODE="{CODE}")', "pageNumber": page, "pageSize": 500,
             "sortColumns": "TRADE_DATE", "sortTypes": 1, "source": "WEB", "client": "WEB"}
        try:
            j = requests.get(url, params=p, timeout=25, headers=UA).json()
        except Exception as exc:  # noqa: BLE001
            log(f"block_trade FAIL page{page}: {type(exc).__name__}")
            break
        data = (j.get("result") or {}).get("data") or []
        if not data:
            break
        rows.extend(data)
        if len(data) < 500:
            break
        page += 1
        throttle(1.0)
    if not rows:
        log("block_trade: empty")
        return
    df = pd.DataFrame(rows)
    df = df.rename(columns={
        "TRADE_DATE": "date", "DEAL_PRICE": "price", "CLOSE_PRICE": "close",
        "PREMIUM_RATIO": "premium_pct", "DEAL_VOLUME": "volume",
        "DEAL_AMT": "amount", "BUYER_NAME": "buyer", "SELLER_NAME": "seller",
        "TRADE_TYPE": "trade_type", "TURNOVER_RATIO": "amount_pct_float",
    })
    keep = [c for c in ["date", "price", "close", "premium_pct", "volume", "amount",
                        "buyer", "seller", "amount_pct_float"] if c in df.columns]
    df = df[keep].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("price", "close", "premium_pct", "volume", "amount", "amount_pct_float"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "premium_pct" in df.columns:
        df["premium_pct"] = df["premium_pct"] * 100  # -> %
    save(df, "block_trade")


def fetch_announcements() -> None:
    """个股公告标题（东财）— 事件时间线的原始素材。"""
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    rows = []
    for page in range(1, 5):
        p = {"sr": -1, "page_size": 50, "page_index": page, "ann_type": "A",
             "client_source": "web", "stock_list": CODE, "f_node": 0, "s_node": 0}
        try:
            j = requests.get(url, params=p, timeout=25, headers=UA).json()
        except Exception as exc:  # noqa: BLE001
            log(f"ann FAIL page{page}: {type(exc).__name__}")
            break
        data = (j.get("data") or {}).get("list") or []
        if not data:
            break
        for it in data:
            rows.append({"date": it.get("notice_date", "")[:10],
                         "title": it.get("title", ""),
                         "type": ",".join(c.get("column_name", "") for c in (it.get("columns") or []))})
        throttle(1.0)
    if not rows:
        log("ann: empty")
        return
    df = pd.DataFrame(rows).drop_duplicates(subset=["date", "title"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date", ascending=False)
    df.to_csv(OUT / "announcements.csv", index=False, encoding="utf-8-sig")
    log(f"ann: {len(df)} rows ({df['date'].min()} .. {df['date'].max()})")



def fetch_lockup() -> None:
    """限售解禁（IPO 后三年解禁是重要压力位）。"""
    df = retry(ak.stock_restricted_release_queue_em, symbol=CODE)
    if df is not None:
        df = df.rename(columns={"序号": "seq", "解禁时间": "date", "解禁数量": "unlock_shares",
                                "解禁股流通市值": "unlock_mktcap", "解禁股东数": "n_holders",
                                "限售股类型": "type"})
        save(df, "lockup")


def fetch_board(start: str, end: str) -> None:
    """所属行业板块指数（玻纤/非金属材料）— 用于板块相对强度。"""
    s, e = start.replace("-", ""), end.replace("-", "")
    df = retry(ak.stock_board_industry_name_em)
    want = ("玻璃", "非金属", "化学制品", "电子元件", "元件")
    if df is not None:
        hit = df[df["板块名称"].str.contains("|".join(want), na=False)]
        log("industry boards: " + ", ".join(hit["板块名称"].tolist()[:12]))
        for _, r in hit.head(4).iterrows():
            h = retry(ak.stock_board_industry_hist_em, symbol=r["板块名称"],
                      start_date=s, end_date=e, period="日k", adjust="")
            if h is not None:
                h = h.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                                      "最高": "high", "最低": "low", "涨跌幅": "pct_chg",
                                      "成交额": "amount", "换手率": "turnover"})
                name = str(abs(hash(r["板块名称"])) % 10**6)
                save(h[["date", "close", "pct_chg", "amount", "turnover"]],
                     f"board_{name}_{r['板块名称'][:4]}")
                time.sleep(0.4)


def fetch_news() -> None:
    """个股新闻（用于事件标记，不做文本挖掘）。"""
    df = retry(ak.stock_news_em, symbol=CODE)
    if df is not None:
        df = df.rename(columns={"关键词": "keyword", "新闻标题": "title", "新闻内容": "content",
                                "发布时间": "date", "文章来源": "source", "新闻链接": "url"})
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date")
        df.to_csv(OUT / "news.csv", index=False, encoding="utf-8-sig")
        log(f"news: {len(df)} rows ({df['date'].min()} .. {df['date'].max()})")


def fetch_comment() -> None:
    """千股千评：机构参与度 / 市场关注度（历史序列）。"""
    df = retry(ak.stock_comment_detail_zlkp_jgcyd_em, symbol=CODE)
    if df is not None:
        df = df.rename(columns={"交易日": "date", "机构参与度": "inst_participation"})
        save(df, "inst_participation")


def fetch_zt_pool(start: str, end: str) -> None:
    """涨跌停/炸板 — 记录本股极端情绪日。"""
    s, e = start.replace("-", ""), end.replace("-", "")
    frames = []
    for fn, tag in ((ak.stock_zt_pool_em, "limit_up"), (ak.stock_zt_pool_zbgc_em, "zhaban")):
        d = retry(fn, date=e)
        if d is not None and len(d):
            sub = d[d["代码"].astype(str).str.zfill(6) == CODE]
            if len(sub):
                sub = sub.assign(tag=tag)
                frames.append(sub)
    if frames:
        out = pd.concat(frames, ignore_index=True)
        out.to_csv(OUT / "zt_pool_today.csv", index=False, encoding="utf-8-sig")
        log(f"zt_pool_today: {len(out)} rows")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-06-01")
    ap.add_argument("--end", default="2026-09-12")
    ap.add_argument("--only", default="", help="逗号分隔的步骤子集，空=全部")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    log(f"code={SYMBOL} window={args.start}..{args.end}")

    steps = {
        "prices": lambda: fetch_prices(args.start, args.end),
        "index": lambda: fetch_index(args.start, args.end),
        "moneyflow": fetch_moneyflow_full,
        "margin": fetch_margin,
        "holders": fetch_holders,
        "lhb": lambda: fetch_lhb(args.start, args.end),
        "block": lambda: fetch_block_trade(args.start, args.end),
        "ann": fetch_announcements,
        "lockup": fetch_lockup,
        "board": lambda: fetch_board(args.start, args.end),
        "news": fetch_news,
        "comment": fetch_comment,
        "zt": lambda: fetch_zt_pool(args.start, args.end),
    }
    selected = [s.strip() for s in args.only.split(",") if s.strip()] or list(steps)
    for name in selected:
        if name not in steps:
            log(f"unknown step: {name}")
            continue
        log(f"--- {name} ---")
        steps[name]()
        throttle()

    manifest = sorted(p.name for p in OUT.glob("*.csv"))
    (OUT / "_manifest.json").write_text(
        json.dumps({"symbol": SYMBOL, "start": args.start, "end": args.end,
                    "files": manifest}, ensure_ascii=False, indent=2))
    log(f"done. {len(manifest)} files in {OUT}")


if __name__ == "__main__":
    main()
