"""导出 2026 年的买卖点信号日志(推荐配置)。

推荐配置 = 趋势滞回带(收盘>MA20×1.05 且 MA20>MA60 建仓;
                        收盘<MA20×0.95 或 MA20<MA60 离场; 中间地带维持)
           + 抄底先手(空仓时 B1/B2/B3 → 0.7 仓)

输出:
  signal_log_2026.csv  — 逐日信号日志(含原因、次日成交价、当时顶部风险标记)
  trades_2026.csv      — 2026 年已实现回合交易
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import signal_engine as se
import strategy as st
import swing_lib as sl

YEAR = ("2026-01-01", "2026-09-11")


def build_with_reason(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    """复刻推荐配置, 同时记录每个状态变化的原因。"""
    p = se.default_params()
    sig = se.sub_signals(df, p)
    c, ma20, ma60 = df["close"], df["ma20"], df["ma60"]
    up = (c > ma20 * (1 + p["buy_band"])) & (ma20 > ma60)
    dn_price = c < ma20 * (1 - p["sell_band"])
    dn_cross = ma20 < ma60
    dn = dn_price | dn_cross
    cn = c.to_numpy(float)
    upv, dpv, dcv, dnv = (up.to_numpy(bool), dn_price.to_numpy(bool),
                          dn_cross.to_numpy(bool), dn.to_numpy(bool))
    b1 = sig["B1_panic"].fillna(False).to_numpy()
    b2 = sig["B2_crash"].fillna(False).to_numpy()
    b3 = sig["B3_snapback"].fillna(False).to_numpy()

    out = np.zeros(len(df))
    reason = np.array([""] * len(df), dtype=object)
    in_pos = False
    for i in range(len(df)):
        if in_pos:
            if dnv[i]:
                in_pos = False
                out[i] = 0.0
                reason[i] = ("卖出:跌破MA20×0.95" if dpv[i] else "卖出:MA20下穿MA60")
                continue
            reason[i] = "持有"
            out[i] = 1.0
        elif upv[i]:
            in_pos, out[i], reason[i] = True, 1.0, "买入:趋势确认(收盘>MA20×1.05且MA20>MA60)"
        elif b2[i] or b1[i] or b3[i]:
            tag = "B2个股崩跌" if b2[i] else ("B1系统恐慌" if b1[i] else "B3强势急回踩")
            in_pos, out[i], reason[i] = True, p["dip_size"], f"买入:抄底先手({tag})"
    return (pd.Series(out, index=df.index, name="target"),
            pd.Series(reason, index=df.index, name="reason"), sig)


def main() -> None:
    df = sl.add_features(sl.load_panel()).replace([np.inf, -np.inf], np.nan)
    tgt, reason, sig = build_with_reason(df)
    op = df["open"]
    exec_px = op.shift(-1)                      # 信号日收盘决策 -> 次日开盘成交
    exec_date = pd.Series(df.index, index=df.index).shift(-1)

    log = pd.DataFrame({
        "收盘价": df["close"], "建议仓位": tgt, "状态": reason,
        "距MA20%": df["dist_ma20"], "MA20": df["ma20"], "MA60": df["ma60"],
        "次日成交价": exec_px, "成交日": exec_date,
    }).loc[YEAR[0]:YEAR[1]]

    chg = log[(log["建议仓位"].diff().fillna(log["建议仓位"].iloc[0]) != 0)
              | (log["状态"].str.startswith("买入") | log["状态"].str.startswith("卖出"))]
    chg = chg.copy()
    if len(chg):
        first = chg.index[0]
        if chg.loc[first, "状态"] == "持有":
            chg.loc[first, "状态"] = "持有(延续2025年底持仓)"

    print("=" * 116)
    print("2026 年买点 / 卖点日志（推荐配置：趋势滞回带 5%/5% + 抄底先手）")
    print(f"窗口 {YEAR[0]} ~ {YEAR[1]}  共 {len(log)} 个交易日")
    print("=" * 116)
    show = chg.copy()
    show["信号日"] = [d.date() for d in show.index]
    show["成交日"] = [d.date() if pd.notna(d) else "" for d in show["成交日"]]
    print(show[["信号日", "收盘价", "状态", "距MA20%", "成交日", "次日成交价", "建议仓位"]]
          .round(2).to_string(index=False))

    # 已实现回合交易
    res = sl.backtest(df.loc[YEAR[0]:YEAR[1]], tgt.loc[YEAR[0]:YEAR[1]])
    tr = pd.DataFrame([{
        "买入日": t.entry_date.date(), "买入价": round(t.entry_px, 2),
        "卖出日": t.exit_date.date(), "卖出价": round(t.exit_px, 2),
        "标的涨跌%": round(t.ret * 100, 1), "持有天": t.hold_days} for t in res.trades])
    print("\n" + "=" * 116)
    print(f"2026 年已实现回合交易（{len(tr)} 笔）")
    print("=" * 116)
    print(tr.to_string(index=False))
    bh = sl.backtest(df.loc[YEAR[0]:YEAR[1]], pd.Series(1.0, index=df.loc[YEAR[0]:YEAR[1]].index))
    print(f"\n组合层面 2026（含成本，这才是可比的数字）:")
    print(f"  策略     收益 {res.metrics['total_return_pct']:7.1f}% | 回撤 {res.metrics['max_drawdown_pct']:6.1f}% | "
          f"Sharpe {res.metrics['sharpe']:.2f} | 在场 {res.metrics['exposure_pct']:.1f}%")
    print(f"  买入持有 收益 {bh.metrics['total_return_pct']:7.1f}% | 回撤 {bh.metrics['max_drawdown_pct']:6.1f}% | "
          f"Sharpe {bh.metrics['sharpe']:.2f}")
    if len(tr):
        win = tr[tr["标的涨跌%"] > 0]
        small = tr[tr["持有天"] <= 3]
        print(f"\n  逐笔：胜率 {len(win)}/{len(tr)} = {len(win)/len(tr)*100:.0f}% | "
              f"最好 {tr['标的涨跌%'].max():+.1f}% | 最差 {tr['标的涨跌%'].min():+.1f}%")
        print(f"  注：'标的涨跌%' 是持仓标的自身的涨跌，抄底先手仓位为 0.7（满仓为 1.0），"
              f"对组合的贡献需再乘以仓位。")
        print(f"  1~3 天的短交易 {len(small)} 笔（多为抄底先手在震荡区被止损）："
              f"合计标的涨跌 {small['标的涨跌%'].sum():+.1f}%，对组合影响很小。")

    print("\n" + "=" * 116)
    print("同期顶部风险信号（推荐配置不下车，仅作观察；D 类信号的定位见 REPORT 4.3 节）")
    print("=" * 116)
    top = sig.loc[YEAR[0]:YEAR[1]]
    topev = top[(top[["D_overheat", "D_leverage", "D_distribute"]].any(axis=1))]
    if len(topev):
        grp = topev.groupby((~topev.index.isin(topev.index)).cumsum())
        for d, g in topev.groupby(pd.Grouper(freq="ME")):
            if len(g) == 0:
                continue
            tags = []
            if g["D_overheat"].any():
                tags.append("过热")
            if g["D_leverage"].any():
                tags.append("杠杆+换手极端")
            if g["D_distribute"].any():
                tags.append("大宗折价派发")
            print(f"  {d.strftime('%Y-%m')}: {len(g):2d} 天触发 — {', '.join(tags)} "
                  f"（{g.index.min().date()} ~ {g.index.max().date()}）")
    print(f"\n同期真正触发离场的只有 'MA20 下穿/跌破' 规则；"
          f"顶部信号若用于减仓，会提前下车并错过主升（见 REPORT 4.3 节回测对比）。")

    show.to_csv("signal_log_2026.csv", encoding="utf-8-sig")
    tr.to_csv("trades_2026.csv", index=False, encoding="utf-8-sig")
    print("\n-> signal_log_2026.csv / trades_2026.csv")


if __name__ == "__main__":
    main()
