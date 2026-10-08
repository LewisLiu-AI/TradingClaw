"""跨标的稳健性检验: 把同一套规则(不做任何再调参)套到其他高波动A股上。

目的: 判断 "MA20/60 + 5%滞回带" 是不是 301526 的过拟合产物。
方法: 同一参数、同一成本模型、同一窗口(2024-06~2026-09), 对比 买入持有 vs 规则。
"""
from __future__ import annotations

import time
from pathlib import Path

import akshare as ak
import numpy as np
import pandas as pd

import swing_lib as sl
import tune_trend as tt

PEERS = [
    ("300308", "sz300308", "中际旭创"), ("300394", "sz300394", "天孚通信"),
    ("002371", "sz002371", "北方华创"), ("688256", "sh688256", "寒武纪"),
    ("002463", "sz002463", "沪电股份"), ("600183", "sh600183", "生益科技"),
    ("601138", "sh601138", "工业富联"), ("300476", "sz300476", "胜宏科技"),
    ("301526", "sz301526", "国际复材"), ("000300", "sh000300", "沪深300(对照)"),
]
CACHE = Path(__file__).parent / "data" / "peers"
START, END = "2024-06-01", "2026-09-11"


def fetch_peer(sym: str) -> pd.DataFrame | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{sym}.csv"
    if f.exists():
        df = pd.read_csv(f, parse_dates=["date"]).set_index("date")
    else:
        try:
            if sym.startswith("sh000") or sym.startswith("sz399"):
                d = ak.stock_zh_index_daily(symbol=sym)
                d = d.reset_index()
                d.columns = ["date", "open", "high", "low", "close", "volume"]
            else:
                d = ak.stock_zh_a_daily(symbol=sym, adjust="qfq")
                d = d.reset_index()
            d["date"] = pd.to_datetime(d["date"])
            df = d[(d["date"] >= START) & (d["date"] <= END)].set_index("date").sort_index()
            df = df[~df.index.duplicated(keep="last")]
            df.to_csv(f, encoding="utf-8-sig")
            time.sleep(1.2)
        except Exception as exc:  # noqa: BLE001
            print(f"  {sym} fetch FAIL: {type(exc).__name__}")
            return None
    return df


def prep(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "turnover" not in out.columns:
        out["turnover"] = 5.0
    out["close_raw"] = out["close"]
    out["prev_close_raw"] = out["close"].shift(1)
    for n in (5, 10, 20, 30, 60, 120):
        out[f"ma{n}"] = out["close"].rolling(n).mean()
    out["ma20_slope"] = (out["ma20"] - out["ma20"].shift(10)) / out["ma20"].shift(10).abs() / 10 * 100
    return out


def main() -> None:
    idx = pd.read_csv("data/idx_cyb.csv", parse_dates=["date"]).set_index("date")["close"]
    rows = []
    for code, sym, name in PEERS:
        df = fetch_peer(sym)
        if df is None or len(df) < 200:
            continue
        df = prep(df)
        # 供抄底层使用的大盘特征
        try:
            feat = sl.add_features(df.assign(idx_cyb=idx.reindex(df.index).ffill()))
        except Exception as exc:  # noqa: BLE001
            print(f"  {name} features FAIL: {exc}")
            feat = df
        feat = feat.replace([np.inf, -np.inf], np.nan)

        pos_core = tt.banded_trend(feat, buy_band=0.05, sell_band=0.05)
        pos_dip = tt.banded_trend(feat, buy_band=0.05, sell_band=0.05, dip=True)
        bh = sl.backtest(feat, pd.Series(1.0, index=feat.index)).metrics
        core = sl.backtest(feat, pos_core).metrics
        dipm = sl.backtest(feat, pos_dip).metrics
        rows.append({
            "标的": name, "bars": len(feat),
            "BH收益%": bh["total_return_pct"], "BH回撤%": bh["max_drawdown_pct"],
            "BH_Calmar": bh["calmar"],
            "核心收益%": core["total_return_pct"], "核心回撤%": core["max_drawdown_pct"],
            "核心_Calmar": core["calmar"], "核心_交易数": core["n_trades"],
            "核心+抄底收益%": dipm["total_return_pct"], "核心+抄底回撤%": dipm["max_drawdown_pct"],
            "核心+抄底_Calmar": dipm["calmar"],
        })
        print(f"  {name} done ({len(feat)} bars)")

    t = pd.DataFrame(rows)
    pd.set_option("display.width", 240)
    print("\n" + "=" * 118)
    print("同一规则(MA20/60, 买带5%, 卖带5%)跨标的检验, 窗口 2024-06~2026-09, 含成本")
    print("=" * 118)
    cols = ["标的", "bars", "BH收益%", "BH回撤%", "BH_Calmar", "核心收益%", "核心回撤%",
            "核心_Calmar", "核心_交易数", "核心+抄底收益%", "核心+抄底回撤%", "核心+抄底_Calmar"]
    print(t[cols].round(2).to_string(index=False))

    print("\n=== 汇总 ===")
    print(f"回撤改善(核心 vs BH): {(t['核心回撤%'] > t['BH回撤%']).sum()}/{len(t)} 只")
    print(f"Calmar 改善: {(t['核心_Calmar'] > t['BH_Calmar']).sum()}/{len(t)} 只")
    print(f"收益改善: {(t['核心收益%'] > t['BH收益%']).sum()}/{len(t)} 只")
    print(f"中位 回撤: BH {-t['BH回撤%'].median():.1f}% -> 核心 {-t['核心回撤%'].median():.1f}%")
    print(f"中位 Calmar: BH {t['BH_Calmar'].median():.2f} -> 核心 {t['核心_Calmar'].median():.2f}")
    t.to_csv("results_cross_check.csv", index=False, encoding="utf-8-sig")
    print("\n-> results_cross_check.csv")


if __name__ == "__main__":
    main()
