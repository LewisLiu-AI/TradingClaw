"""海外因子 gate 的实盘效果检验(决定性测试)

教训来自第 11 节: 统计最强的变量(量比 p=0.010)接到策略上反而把收益从 1051% 打到 765%,
因为 gate 与入场条件逻辑冲突。所以必须直接看回测, 不能只看 p 值。

时序: 美股 T 日 16:00 ET 收盘 = 北京 T+1 凌晨, 因此美股 T 日数据在中国 T+1 开盘前已知,
      用于"T 日收盘决策 / T+1 开盘成交"无前视 (比 A 股自身数据还宽松)。

对比:
  基准          : 推荐配置(趋势滞回带 5%/5% + 先手层 B1|B2)
  G-两融        : 先手层需 沪市两融20日变化>0              (第 11 节的结论)
  G-费半        : 先手层需 费城半导体20日变化>0
  G-SOX/纳指    : 先手层需 费城半导体-纳指 20日相对强弱>0  (口径A最强变量)
  G-纳指        : 先手层需 纳斯达克20日变化>0
  G-费半+两融   : 两者同时>0
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import analyze_macro as am
import cross_check as cc
import signal_engine as se
import swing_lib as sl
import tune_trend as tt

pd.set_option("display.width", 250)
FULL = ("2024-06-01", "2026-09-11")
WINS = {"全样本": FULL, "2025": ("2025-01-01", "2025-12-31"),
        "2026": ("2026-01-01", "2026-09-11")}
KEEP_SLIM = ("B1", "B2")


def global_daily() -> pd.DataFrame:
    """海外因子日频序列, 对齐到 A 股交易日(ffill)。"""
    g = {}
    for tag in ("sox", "ixic", "vix", "gold", "oil", "us10y", "dxy", "hsi"):
        try:
            d = pd.read_csv(f"data/global/{tag}.csv", parse_dates=["date"]).set_index("date")["close"]
            g[tag] = d
        except Exception:  # noqa: BLE001
            print(f"  缺 {tag}")
    df = pd.DataFrame(g).sort_index()
    out = pd.DataFrame(index=df.index)
    out["sox_ret20"] = df["sox"].pct_change(20) * 100
    out["ixic_ret20"] = df["ixic"].pct_change(20) * 100
    out["sox_vs_ixic"] = out["sox_ret20"] - out["ixic_ret20"]
    out["vix"] = df["vix"]
    out["gold_ret20"] = df["gold"].pct_change(20) * 100
    out["oil_ret20"] = df["oil"].pct_change(20) * 100
    out["hsi_ret20"] = df["hsi"].pct_change(20) * 100
    return out


def pos_with_gate(feat: pd.DataFrame, mkt: pd.DataFrame, g: pd.DataFrame,
                  gate: str | None) -> pd.Series:
    sig = se.sub_signals(feat)
    allow = pd.Series(False, index=feat.index)
    for k in KEEP_SLIM:
        allow = allow | sig[{"B1": "B1_panic", "B2": "B2_crash"}[k]].fillna(False)
    if gate:
        m = mkt.reindex(feat.index).ffill()
        gg = g.reindex(feat.index).ffill()
        conds = {
            "两融>0": m["mkt_margin_chg20"] > 0,
            "费半>0": gg["sox_ret20"] > 0,
            "SOX/纳指>0": gg["sox_vs_ixic"] > 0,
            "纳指>0": gg["ixic_ret20"] > 0,
            "费半>0且两融>0": (gg["sox_ret20"] > 0) & (m["mkt_margin_chg20"] > 0),
            "VIX<中位": gg["vix"] < gg["vix"].rolling(250).median(),
        }
        allow = allow & conds[gate].fillna(False)
    base = tt.banded_trend(feat, buy_band=0.05, sell_band=0.05, dip=True)
    off = tt.banded_trend(feat, buy_band=0.05, sell_band=0.05, dip=False)
    p = base.to_numpy(float)
    is_dip = (p > 0) & (np.abs(p - 0.7) < 1e-6) & (off.to_numpy(float) < 1e-6)
    p[is_dip & ~allow.to_numpy()] = 0.0
    return pd.Series(p, index=feat.index)


def st_(feat, pos, a, b) -> dict:
    m = sl.backtest(feat.loc[a:b], pos.loc[a:b]).metrics
    return {"收益%": m["total_return_pct"], "回撤%": m["max_drawdown_pct"],
            "Sharpe": m["sharpe"], "Calmar": m["calmar"], "交易数": m["n_trades"]}


GATES = {
    "基准(无gate)": None,
    "G-两融>0": "两融>0",
    "G-SOX/纳指>0": "SOX/纳指>0",
    "G-费半>0": "费半>0",
    "G-纳指>0": "纳指>0",
    "G-费半>0且两融>0": "费半>0且两融>0",
    "G-VIX<250日中位": "VIX<中位",
}


def main() -> None:
    g = global_daily()
    print(f"海外因子: {len(g)} 行 {g.index.min().date()}..{g.index.max().date()}")
    print(f"最新: 费半20日 {g['sox_ret20'].iloc[-1]:+.1f}% | 纳指20日 {g['ixic_ret20'].iloc[-1]:+.1f}% | "
          f"SOX/纳指 {g['sox_vs_ixic'].iloc[-1]:+.1f}pp | VIX {g['vix'].iloc[-1]:.1f}")
    mkt = am.load_market()
    idx = pd.read_csv("data/idx_cyb.csv", parse_dates=["date"]).set_index("date")["close"]
    feat = sl.add_features(sl.load_panel()).replace([np.inf, -np.inf], np.nan)

    print("\n" + "=" * 120)
    print("1. 国际复材: 各 gate 的回测效果")
    print("=" * 120)
    res = {name: {w: st_(feat, pos_with_gate(feat, mkt, g, gt), *WINS[w]) for w in WINS}
           for name, gt in GATES.items()}
    for w in WINS:
        print(f"\n--- {w} ---")
        print(pd.DataFrame({k: v[w] for k, v in res.items()}).T.round(2).to_string())
    print("\n--- 买入持有 ---")
    print(pd.DataFrame([st_(feat, pd.Series(1.0, index=feat.index), *FULL)]).round(2).to_string(index=False))

    print("\n" + "=" * 120)
    print("2. 跨 9 只标的 (2025-01~2026-09): 基准 vs 各 gate")
    print("=" * 120)
    rows = []
    for code, sym, name in am.SYMBOLS:
        d = cc.fetch_peer(sym)
        if d is None or len(d) < 250:
            continue
        f = sl.add_features(cc.prep(d).assign(idx_cyb=idx.reindex(d.index).ffill()))
        f = f.replace([np.inf, -np.inf], np.nan)
        a, b = "2025-01-01", "2026-09-11"
        r = {"标的": name}
        for gname, gt in GATES.items():
            m = st_(f, pos_with_gate(f, mkt, g, gt), a, b)
            r[f"{gname}|收益"] = m["收益%"]
            r[f"{gname}|交易"] = m["交易数"]
            r[f"{gname}|Sharpe"] = m["Sharpe"]
        rows.append(r)
    t = pd.DataFrame(rows)
    base = "基准(无gate)"
    out = []
    for gname in GATES:
        if gname == base:
            continue
        out.append({
            "gate": gname,
            "中位收益%": t[f"{gname}|收益"].median(),
            "收益改善": f"{(t[f'{gname}|收益'] > t[f'{base}|收益']).sum()}/{len(t)}",
            "中位Sharpe": t[f"{gname}|Sharpe"].median(),
            "Sharpe改善": f"{(t[f'{gname}|Sharpe'] > t[f'{base}|Sharpe']).sum()}/{len(t)}",
            "总交易数": int(t[f"{gname}|交易"].sum()),
            "交易变化": int(t[f"{gname}|交易"].sum() - t[f"{base}|交易"].sum()),
        })
    print(pd.DataFrame(out).round(2).to_string(index=False))
    print(f"\n基准 中位收益 {t[f'{base}|收益'].median():.1f}% | 总交易 {int(t[f'{base}|交易'].sum())} 笔")
    t.to_csv("results_global_gate.csv", index=False, encoding="utf-8-sig")
    print("\n-> results_global_gate.csv")


if __name__ == "__main__":
    main()
