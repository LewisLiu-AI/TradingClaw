"""跨标的: 比较几种结构性变体, 找出在"削回撤 vs 保上行"上权衡更好的规则。

9 只高波动A股 × 同一窗口, 同一成本模型。变体只做结构性改动, 不做逐股调参。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import swing_lib as sl
import cross_check as cc

BH = "V0 买入持有"


def pos_banded(df, buy=0.0, sell=0.0, cross=True, naive=False) -> pd.Series:
    ma20, ma60, c = df["ma20"], df["ma60"], df["close"]
    up = c > ma20 * (1 + buy)
    dn = c < ma20 * (1 - sell)
    if cross:
        up &= ma20 > ma60
        dn |= ma20 < ma60
    out, s = np.zeros(len(df)), False
    for i in range(len(df)):
        if s:
            if dn.iloc[i]:
                s = False
        elif up.iloc[i]:
            s = True
        out[i] = 1.0 if s else 0.0
    return pd.Series(out, index=df.index)


def pos_graded(df, deep=0.10) -> pd.Series:
    """分级: 站上MA20=满仓; 跌破MA20但在MA20*(1-deep)之上=半仓; 再低或MA20<MA60=空仓。"""
    ma20, ma60, c = df["ma20"], df["ma60"], df["close"]
    p = pd.Series(0.0, index=df.index)
    p[c > ma20] = 1.0
    p[(c <= ma20) & (c > ma20 * (1 - deep))] = 0.5
    p[(c < ma20 * (1 - deep)) | (ma20 < ma60)] = 0.0
    return p


def pos_trail(df, trail=0.25) -> pd.Series:
    out, s, peak = np.zeros(len(df)), False, 0.0
    c = df["close"].to_numpy(float)
    for i in range(len(df)):
        if s:
            peak = max(peak, c[i])
            if c[i] <= peak * (1 - trail):
                s = False
        else:
            s, peak = True, c[i]
        out[i] = 1.0 if s else 0.0
    return pd.Series(out, index=df.index)


def pos_trail_reentry(df, trail=0.25, buy=0.0, cross=True) -> pd.Series:
    """追踪止损 + 带条件的回补(需重新站上均线, 而不是次日无条件买回)。

    V6 的缺陷在于止损后无条件回补, 会在下跌途中被反复打脸。
    """
    ma20, ma60, c = df["ma20"], df["ma60"], df["close"]
    up = c > ma20 * (1 + buy)
    if cross:
        up = up & (ma20 > ma60)
    cn = c.to_numpy(float)
    upv = up.to_numpy(bool)
    out, s, peak = np.zeros(len(df)), False, 0.0
    for i in range(len(df)):
        if s:
            peak = max(peak, cn[i])
            if cn[i] <= peak * (1 - trail):
                s = False
                continue
            out[i] = 1.0
        elif upv[i]:
            s, peak, out[i] = True, cn[i], 1.0
    return pd.Series(out, index=df.index)


VARIANTS = {
    "V0 买入持有": None,
    "V1 MA20/60 买5%卖5%": lambda d: pos_banded(d, 0.05, 0.05),
    "V2 MA20/60 买0%卖5%": lambda d: pos_banded(d, 0.0, 0.05),
    "V3 MA20/60 买0%卖8%": lambda d: pos_banded(d, 0.0, 0.08),
    "V5 分级(满/半/空)": lambda d: pos_graded(d, 0.10),
    "V6 满仓+25%追踪(无条件回补)": lambda d: pos_trail(d, 0.25),
    "V7 满仓+25%追踪+MA20回补": lambda d: pos_trail_reentry(d, 0.25, 0.0, cross=False),
    "V8 满仓+25%追踪+MA20/60回补": lambda d: pos_trail_reentry(d, 0.25, 0.0, cross=True),
    "V9 满仓+20%追踪+MA20/60回补": lambda d: pos_trail_reentry(d, 0.20, 0.0, cross=True),
    "V10 满仓+25%追踪+回补需高于MA20 5%": lambda d: pos_trail_reentry(d, 0.25, 0.05, cross=True),
}


def main() -> None:
    idx = pd.read_csv("data/idx_cyb.csv", parse_dates=["date"]).set_index("date")["close"]
    data = {}
    for code, sym, name in cc.PEERS:
        if name.startswith("沪深"):
            continue
        df = cc.fetch_peer(sym)
        if df is None or len(df) < 200:
            continue
        data[name] = cc.prep(df)

    rows = []
    for name, df in data.items():
        for vname, fn in VARIANTS.items():
            pos = (pd.Series(1.0, index=df.index) if fn is None else fn(df))
            m = sl.backtest(df, pos).metrics
            rows.append({"标的": name, "变体": vname, "收益%": m["total_return_pct"],
                         "回撤%": m["max_drawdown_pct"], "Calmar": m["calmar"],
                         "Sharpe": m["sharpe"], "交易数": m["n_trades"]})
    t = pd.DataFrame(rows)
    bh = t[t["变体"] == BH].set_index("标的")

    print("=" * 128)
    print("跨标的(9只)结构变体对比 — 窗口 2024-06~2026-09, 含成本, 无再调参")
    print("=" * 128)
    out = []
    for vname in VARIANTS:
        sub = t[t["变体"] == vname].set_index("标的")
        j = sub.join(bh, rsuffix="_bh")
        out.append({
            "变体": vname,
            "中位收益%": sub["收益%"].median(),
            "中位回撤%": sub["回撤%"].median(),
            "中位Calmar": sub["Calmar"].median(),
            "中位Sharpe": sub["Sharpe"].median(),
            "回撤改善": f"{(j['回撤%'] > j['回撤%_bh']).sum()}/9",
            "收益改善": f"{(j['收益%'] > j['收益%_bh']).sum()}/9",
            "Calmar改善": f"{(j['Calmar'] > j['Calmar_bh']).sum()}/9",
            "收益中位比BH": (j["收益%"] / j["收益%_bh"]).median(),
        })
    print(pd.DataFrame(out).round(2).to_string(index=False))

    print("\n" + "=" * 128)
    print("逐标的明细 (收益% / 回撤%)")
    print("=" * 128)
    wide = t.pivot_table(index="标的", columns="变体", values=["收益%", "回撤%"]).round(1)
    print(wide.to_string())
    t.to_csv("results_variants_cross.csv", index=False, encoding="utf-8-sig")
    print("\n-> results_variants_cross.csv")


if __name__ == "__main__":
    main()
