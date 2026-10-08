"""用正确的实现重算"先手层筛选 / 宏观 gate"的全部结论。

背景(修正的方法学 bug):
  早期 macro_gate_final.py / filter_test.py / macro_global_*.py 用"**过滤既有轨迹**"
  实现"先手层只保留部分子策略"(先跑全集合状态机, 再在部分日子把 0.7 清零)。
  该做法只能删不能加, 会连带丢掉受限集合本应在次日发生的新入场 ——
  实测 2026-07-10 那次 B1 入场就被丢掉了(全集合在 07-09 经 A_pullback 入场、
  07-10 被打出, 于是 07-10 的 B1 新入场在轨迹里不存在)。
  正确做法: 用受限信号集**重跑状态机**。本脚本统一用 swing_strategy.target_position
  的 dip_mask 参数实现, 结果取代 REPORT 第 11.3/11.4/11.5/13.2 节的旧数字。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import cross_check as cc
import macro_global_gate as mgg
import swing_lib as sl
import swing_strategy as sw

pd.set_option("display.width", 250)
FULL = ("2024-06-01", "2026-09-11")
WINS = {"全样本": FULL, "2025": ("2025-01-01", "2025-12-31"),
        "2026": ("2026-01-01", "2026-09-11")}
PEERS = [p for p in cc.PEERS if not p[2].startswith("沪深")]


def load_env() -> tuple[pd.Series, pd.Series]:
    idx = pd.read_csv("data/idx_cyb.csv", parse_dates=["date"]).set_index("date")["close"]
    mg = pd.read_csv("data/mkt_margin.csv", parse_dates=["date"]).set_index("date")
    return idx, mg["mkt_rz_balance_sh"]


IDX, MARGIN = load_env()


def prep(df: pd.DataFrame, name: str) -> pd.DataFrame:
    d = sw.build_features(df)
    d = sw.attach_market(d, IDX)
    d = sw.attach_margin_gate(d, MARGIN)
    return d


def fuxcai() -> pd.DataFrame:
    d = pd.read_csv("data/px_qfq.csv", parse_dates=["date"]).set_index("date")
    if d["turnover"].max() < 1.5:
        d["turnover"] = d["turnover"] * 100
    return prep(d, "国际复材")


def peer(name_sym) -> pd.DataFrame | None:
    code, sym, name = name_sym
    d = cc.fetch_peer(sym)
    if d is None or len(d) < 250:
        return None
    return prep(d, name)


def pos_for(d: pd.DataFrame, keep: tuple, gate: str | None = None,
            scale: str | None = None, preset: str = "balanced") -> pd.Series:
    mask = sw.dip_mask_of(d, keep)
    if gate == "margin":
        mask = mask & (d["mkt_margin_chg20"] > 0).fillna(False)
    elif gate == "sox":
        g = mgg.global_daily().reindex(d.index).ffill()
        mask = mask & (g["sox_ret20"] > 0).fillna(False)
    sc = None
    if scale == "sox":
        g = mgg.global_daily().reindex(d.index).ffill()
        sc = pd.Series(np.where(g["sox_ret20"] > 0, 1.0, 0.5), index=d.index)
    elif scale == "margin":
        sc = pd.Series(np.where(d["mkt_margin_chg20"] > 0, 1.0, 0.5), index=d.index)
    return sw.target_position(d, preset=preset, dip_mask=mask, dip_scale=sc)[0]


VARIANTS = {
    "全集合 A|B1|B2|B3|C": dict(keep=("A", "B1", "B2", "B3", "C")),
    "无B3 A|B1|B2|C": dict(keep=("A", "B1", "B2", "C")),
    "精简 B1|B2": dict(keep=("B1", "B2")),
    "精简+两融gate": dict(keep=("B1", "B2"), gate="margin"),
    "精简+两融缩放": dict(keep=("B1", "B2"), scale="margin"),
    "精简+费半gate": dict(keep=("B1", "B2"), gate="sox"),
    "精简+费半缩放": dict(keep=("B1", "B2"), scale="sox"),
    "全集合+两融gate": dict(keep=("A", "B1", "B2", "B3", "C"), gate="margin"),
}


def metrics(d: pd.DataFrame, pos: pd.Series, a: str, b: str) -> dict:
    r = sw.backtest(d.loc[a:b], pos.loc[a:b])["metrics"]
    return {"收益%": r["total_return_pct"], "回撤%": r["max_drawdown_pct"],
            "Sharpe": r["sharpe"], "Calmar": r["calmar"], "交易数": r["n_trades"]}


def main() -> None:
    d0 = fuxcai()
    print("=" * 124)
    print("1. 国际复材（正确实现：用 dip_mask 重跑状态机）")
    print("=" * 124)
    res = {n: {w: metrics(d0, pos_for(d0, **kw), *WINS[w]) for w in WINS}
           for n, kw in VARIANTS.items()}
    for w in WINS:
        print(f"\n--- {w} ---")
        print(pd.DataFrame({k: v[w] for k, v in res.items()}).T.round(2).to_string())
    bh = {w: metrics(d0, pd.Series(1.0, index=d0.index), *WINS[w]) for w in WINS}
    print("\n--- 买入持有 ---")
    print(pd.DataFrame(bh).T.round(2).to_string())
    print(f"\n注: 对比旧报告数字 —— 精简(B1+B2) 全样本旧值 1050.63%/24笔(错误实现), "
          f"正确值 {res['精简 B1|B2']['全样本']['收益%']:.2f}%/{res['精简 B1|B2']['全样本']['交易数']:.0f}笔")

    print("\n" + "=" * 124)
    print("2. 跨 9 只标的 (2025-01~2026-09)")
    print("=" * 124)
    rows = []
    for item in PEERS:
        d = peer(item)
        if d is None:
            continue
        r = {"标的": item[2]}
        for n, kw in VARIANTS.items():
            m = metrics(d, pos_for(d, **kw), "2025-01-01", "2026-09-11")
            r[f"{n}|收益"] = m["收益%"]
            r[f"{n}|Sharpe"] = m["Sharpe"]
            r[f"{n}|回撤"] = m["回撤%"]
            r[f"{n}|交易"] = m["交易数"]
        rows.append(r)
    t = pd.DataFrame(rows)
    base = "精简 B1|B2"
    print(f"\n基准 {base}: 中位收益 {t[f'{base}|收益'].median():.1f}% | 均值 "
          f"{t[f'{base}|收益'].mean():.1f}% | 中位回撤 {t[f'{base}|回撤'].median():.1f}% | "
          f"总交易 {int(t[f'{base}|交易'].sum())}")
    print(f"\n{'变体':<22}{'中位收益%':>10}{'均值%':>10}{'中位回撤%':>11}"
          f"{'收益改善':>10}{'Sharpe改善':>11}{'回撤改善':>10}{'总交易':>8}")
    for n in list(VARIANTS)[:-1]:
        if n == base:
            continue
        print(f"{n:<22}{t[f'{n}|收益'].median():>10.1f}{t[f'{n}|收益'].mean():>10.1f}"
              f"{t[f'{n}|回撤'].median():>11.1f}"
              f"{int((t[f'{n}|收益'] > t[f'{base}|收益']).sum()):>7}/9"
              f"{int((t[f'{n}|Sharpe'] > t[f'{base}|Sharpe']).sum()):>8}/9"
              f"{int((t[f'{n}|回撤'] > t[f'{base}|回撤']).sum()):>7}/9"
              f"{int(t[f'{n}|交易'].sum()):>8}")
    print(f"\n对照 全集合 A|B1|B2|B3|C: 中位 {t['全集合 A|B1|B2|B3|C|收益'].median():.1f}% | "
          f"总交易 {int(t['全集合 A|B1|B2|B3|C|交易'].sum())}")
    print(f"对照 无B3 A|B1|B2|C   : 中位 {t['无B3 A|B1|B2|C|收益'].median():.1f}% | "
          f"总交易 {int(t['无B3 A|B1|B2|C|交易'].sum())}")

    print("\n" + "=" * 124)
    print("3. 逐标的明细 (收益% / 交易数)")
    print("=" * 124)
    for n in VARIANTS:
        line = " | ".join(f"{r['标的']}:{r[f'{n}|收益']:.0f}%({int(r[f'{n}|交易'])})"
                          for _, r in t.iterrows())
        print(f"  {n:<20} {line}")
    t.to_csv("results_rerun_correct.csv", index=False, encoding="utf-8-sig")
    print("\n-> results_rerun_correct.csv")


if __name__ == "__main__":
    main()
