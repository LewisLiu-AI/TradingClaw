"""信号级过滤 vs 月份级(宏观)过滤 —— 哪个更能"砍掉没必要的交易"?

三种过滤方式对比(跨 9 只标的 + 国际复材):
  F0 现配置        : 先手层 = A_pullback | B1 | B2 | B3 | C_breakout
  F1 砍掉B3        : 先手层 = B1 | B2            (B3 事后看最容易接刀)
  F2 只留B1+B2且大盘不崩: 先手层 = (B1|B2) 且 创业板指不在急跌中
  F3 两融gate      : 先手层 需 全市场两融余额20日变化 > 0 (统计最稳的宏观变量)
  F4 B1+B2 + 两融gate
评价维度: 收益、回撤、Sharpe、Calmar、交易笔数(越低越好, 目标就是砍掉无谓交易)。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import analyze_macro as am
import cross_check as cc
import signal_engine as se
import strategy as st
import swing_lib as sl
import tune_trend as tt

pd.set_option("display.width", 240)
WINS = {"25-01~26-09": ("2025-01-01", "2026-09-11"),
        "2026": ("2026-01-01", "2026-09-11")}


def dip_entry_mask(feat: pd.DataFrame, keep: tuple, mkt: pd.DataFrame | None,
                   margin_gate: bool) -> np.ndarray:
    """按选定的子策略构造"允许先手"的掩码。"""
    sig = se.sub_signals(feat)
    cols = {"A": "A_pullback", "B1": "B1_panic", "B2": "B2_crash",
            "B3": "B3_snapback", "C": "C_breakout"}
    m = pd.Series(False, index=feat.index)
    for k in keep:
        m = m | sig[cols[k]].fillna(False)
    if margin_gate and mkt is not None:
        mg = mkt["mkt_margin_chg20"].reindex(feat.index).ffill() > 0
        m = m & mg.fillna(False)
    return m.to_numpy()


def build_pos(feat: pd.DataFrame, allow: np.ndarray) -> pd.Series:
    """趋势层不变, 只按 allow 过滤先手层。"""
    base = tt.banded_trend(feat, buy_band=0.05, sell_band=0.05, dip=True)
    off = tt.banded_trend(feat, buy_band=0.05, sell_band=0.05, dip=False)
    p = base.to_numpy(float)
    is_dip = (p > 0) & (np.abs(p - 0.7) < 1e-6) & (off.to_numpy(float) < 1e-6)
    p[is_dip & ~allow] = 0.0
    return pd.Series(p, index=feat.index)


VARIANTS = {
    "F0 现配置(A|B1|B2|B3|C)": (("A", "B1", "B2", "B3", "C"), False),
    "F1 砍掉B3(A|B1|B2|C)": (("A", "B1", "B2", "C"), False),
    "F2 只留B1+B2": (("B1", "B2"), False),
    "F3 现配置+两融gate": (("A", "B1", "B2", "B3", "C"), True),
    "F4 B1+B2+两融gate": (("B1", "B2"), True),
}


def main() -> None:
    mkt = am.load_market()
    idx = pd.read_csv("data/idx_cyb.csv", parse_dates=["date"]).set_index("date")["close"]

    rows = []
    stock_data = {}
    for code, sym, name in am.SYMBOLS:
        d = cc.fetch_peer(sym)
        if d is None or len(d) < 200:
            continue
        d = cc.prep(d).assign(idx_cyb=idx.reindex(d.index).ffill())
        feat = sl.add_features(d).replace([np.inf, -np.inf], np.nan)
        stock_data[name] = feat
        for vname, (keep, mgate) in VARIANTS.items():
            allow = dip_entry_mask(feat, keep, mkt, mgate)
            pos = build_pos(feat, allow)
            for wname, (a, b) in WINS.items():
                m = sl.backtest(feat.loc[a:b], pos.loc[a:b]).metrics
                rows.append({"标的": name, "变体": vname, "窗口": wname,
                             "收益%": m["total_return_pct"], "回撤%": m["max_drawdown_pct"],
                             "Sharpe": m["sharpe"], "Calmar": m["calmar"],
                             "交易数": m["n_trades"]})
    t = pd.DataFrame(rows)

    print("=" * 128)
    print("1. 跨 9 只标的汇总 (2025-01~2026-09): 谁在砍交易的同时没砍掉收益?")
    print("=" * 128)
    out = []
    for v in VARIANTS:
        sub = t[(t["变体"] == v) & (t["窗口"] == "25-01~26-09")]
        base = t[(t["变体"] == "F0 现配置(A|B1|B2|B3|C)") & (t["窗口"] == "25-01~26-09")].set_index("标的")
        s = sub.set_index("标的")
        out.append({
            "变体": v,
            "中位收益%": s["收益%"].median(), "中位回撤%": s["回撤%"].median(),
            "中位Sharpe": s["Sharpe"].median(), "中位Calmar": s["Calmar"].median(),
            "总交易数": int(s["交易数"].sum()),
            "收益改善只数": int((s["收益%"] > base["收益%"]).sum()),
            "回撤改善只数": int((s["回撤%"] > base["回撤%"]).sum()),
            "Calmar改善只数": int((s["Calmar"] > base["Calmar"]).sum()),
        })
    res = pd.DataFrame(out)
    res["交易数变化"] = res["总交易数"] - int(res.loc[0, "总交易数"])
    print(res.round(2).to_string(index=False))

    print("\n" + "=" * 128)
    print("2. 国际复材 明细")
    print("=" * 128)
    g = t[t["标的"] == "国际复材"].pivot_table(
        index="变体", columns="窗口", values=["收益%", "回撤%", "Sharpe", "交易数"])
    print(g.round(2).to_string())

    print("\n" + "=" * 128)
    print("3. 逐标的: 收益% / 交易数 (2025-01~2026-09)")
    print("=" * 128)
    for v in VARIANTS:
        s = t[(t["变体"] == v) & (t["窗口"] == "25-01~26-09")].set_index("标的")
        line = " | ".join(f"{k}:{r['收益%']:.0f}%({int(r['交易数'])})" for k, r in s.iterrows())
        print(f"  {v:26s} {line}")

    t.to_csv("results_filter_variants.csv", index=False, encoding="utf-8-sig")
    res.to_csv("results_filter_summary.csv", index=False, encoding="utf-8-sig")
    print("\n-> results_filter_variants.csv / results_filter_summary.csv")


if __name__ == "__main__":
    main()
