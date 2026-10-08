"""抓取市场级(宏观)数据, 用于"可交易月份"过滤研究。

可得性说明:
  - 全市场两融余额(深/沪)     : akshare, 2010 起全历史  ✓
  - 指数行情(上证/中证全指/深证成指) : 东财直连, 新浪兜底  ✓
  - 北向资金                  : 2024 年后已停止逐日披露  ✗
  - 全市场涨跌家数/涨停家数    : 仅有当日快照, 无历史     ✗
  - 大盘资金流(上证口径)       : 东财 push2his, 代理不稳, 尽力抓
"""
from __future__ import annotations

import time
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd
import requests

OUT = Path(__file__).parent / "data"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
F2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
COLS = ["date", "open", "close", "high", "low", "volume", "amount",
        "amplitude", "pct_chg", "change", "turnover"]


def log(m: str) -> None:
    print(f"[macro] {m}", flush=True)


def em_kline(secid: str, beg: str = "20240101", end: str = "20260912") -> pd.DataFrame | None:
    for i in range(4):
        try:
            j = requests.get(KLINE_URL, timeout=20, headers=UA, params={
                "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6", "fields2": F2,
                "klt": 101, "fqt": 1, "beg": beg, "end": end,
                "ut": "fa5fd1943c7b386f172d6893dbfba10b"}).json()
            kl = (j.get("data") or {}).get("klines")
            if kl:
                df = pd.DataFrame([dict(zip(COLS, k.split(","))) for k in kl])
                df["date"] = pd.to_datetime(df["date"])
                for c in df.columns[1:]:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                return df.set_index("date")
        except Exception as exc:  # noqa: BLE001
            log(f"  em retry {i+1}: {type(exc).__name__}")
        time.sleep(2)
    return None


def sina_index(sym: str) -> pd.DataFrame | None:
    try:
        d = ak.stock_zh_index_daily(symbol=sym).reset_index()
        d["date"] = pd.to_datetime(d["date"])
        return d[(d["date"] >= "2024-01-01")].set_index("date").sort_index()
    except Exception as exc:  # noqa: BLE001
        log(f"  sina {sym} fail: {type(exc).__name__}")
        return None


def save(df: pd.DataFrame | None, name: str, date_col: str = "date") -> None:
    if df is None or len(df) == 0:
        log(f"{name}: 空, 跳过")
        return
    if date_col and date_col in getattr(df, "columns", []):
        df = df.set_index(date_col)
    df.index.name = "date"
    df.to_csv(OUT / f"{name}.csv", encoding="utf-8-sig")
    log(f"{name}: {len(df)} 行 {df.index.min().date()}..{df.index.max().date()}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # 1) 宽基指数(含成交额) — 覆盖市场规模与风格
    for secid, sym, name in (("1.000001", "sh000001", "mkt_sse"),      # 上证综指
                             ("1.000985", "sh000985", "mkt_csi_all"),  # 中证全指
                             ("0.399001", "sz399001", "mkt_szse"),     # 深证成指
                             ("1.000905", "sh000905", "mkt_csi500"),   # 中证500(小盘风格)
                             ("1.000016", "sh000016", "mkt_sse50")):   # 上证50(大盘风格)
        df = em_kline(secid) or sina_index(sym)
        save(df, name)
        time.sleep(1.2)

    # 2) 全市场两融余额 — 市场级杠杆
    #    ⚠️ akshare 的**深市**两融数据在 2024-06~2025-06 系统性缺失 177 个交易日。
    #       若用"两市合计 + ffill", 缺口期会变成常数, 伪造出"杠杆无变化"的假信号
    #       (研究早期就踩过这个坑)。因此额外保存**沪市单边**序列(完整 653/653,
    #       占全市场约 51%)作为市场杠杆代理, 分析一律用 mkt_rz_balance_sh。
    legs = {}
    for fn, tag in ((ak.macro_china_market_margin_sz, "sz"),
                    (ak.macro_china_market_margin_sh, "sh")):
        try:
            d = fn()
            d["日期"] = pd.to_datetime(d["日期"])
            d = d.set_index("日期").sort_index()
            d = d[d.index >= "2024-01-01"]
            legs[tag] = d[["融资余额", "融资买入额"]]
            log(f"margin_{tag}: {len(d)} 行, 非空 {d['融资余额'].notna().sum()}")
        except Exception as exc:  # noqa: BLE001
            log(f"margin_{tag} FAIL: {type(exc).__name__}")
        time.sleep(1.0)
    if "sh" in legs:
        m = legs["sh"].rename(columns={
            "融资余额": "mkt_rz_balance_sh", "融资买入额": "mkt_rz_buy_sh"}) / 1e8
        if "sz" in legs:
            sz = legs["sz"]
            m["mkt_rz_balance_total"] = (sz["融资余额"] + legs["sh"]["融资余额"]) / 1e8
        else:
            m["mkt_rz_balance_total"] = np.nan
        m.index.name = "date"
        save(m[["mkt_rz_balance_total", "mkt_rz_balance_sh", "mkt_rz_buy_sh"]],
             "mkt_margin", date_col="")
        log(f"mkt_margin: 沪市单边非空 {m['mkt_rz_balance_sh'].notna().sum()}/{len(m)}, "
            f"两市合计非空 {m['mkt_rz_balance_total'].notna().sum()}/{len(m)}")

    # 3) 大盘资金流(上证口径, 尽力)
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    for i in range(3):
        try:
            j = requests.get(url, timeout=20, headers=UA, params={
                "lmt": 0, "klt": 101, "secid": "1.000001",
                "fields1": "f1,f2,f3,f7",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
                "ut": "b2884a393a59ad64002292a3e90d46a5"}).json()
            kl = (j.get("data") or {}).get("klines") or []
            if kl:
                cols = ["date", "main_net", "small_net", "mid_net", "big_net", "super_net",
                        "main_pct", "small_pct", "mid_pct", "big_pct", "super_pct",
                        "close", "pct_chg", "x13", "x14"][:len(kl[0].split(","))]
                d = pd.DataFrame([dict(zip(cols, k.split(","))) for k in kl])
                d["date"] = pd.to_datetime(d["date"])
                for c in d.columns[1:]:
                    d[c] = pd.to_numeric(d[c], errors="coerce")
                d["mkt_main_net"] = d["main_net"] / 1e8   # 亿元
                save(d.set_index("date")[["mkt_main_net", "main_pct", "close", "pct_chg"]], "mkt_fundflow")
            break
        except Exception as exc:  # noqa: BLE001
            log(f"  fundflow retry {i+1}: {type(exc).__name__}")
        time.sleep(2)


if __name__ == "__main__":
    main()
