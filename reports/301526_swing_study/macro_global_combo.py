"""海外/本土信息能否在"精简(B1+B2)"之上再加价值?

修正说明: 初版脚本构建了 keep 掩码却未接入仓位, 导致 mode="精简" 实际等于不过滤。
本脚本把"选择哪些子策略(keep)""是否阻断(gate)""仓位缩放(scale)"三件事分开处理。

组合(全部先做 keep=B1+B2 的筛选):
  C0 精简            : 仅 B1+B2
  C1 精简+两融gate    : 再加 沪市两融20日变化>0 才允许        (第11节结论)
  C2 精简+两融缩放    : 两融>0 时 0.7 仓, 否则 0.35 仓
  C3 精简+费半gate    : 再加 费城半导体20日变化>0 才允许      (口径A最强海外变量)
  C4 精简+费半缩放    : 费半>0 时 0.7 仓, 否则 0.35 仓
  C5 精简+两融gate+费半缩放
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import analyze_macro as am
import cross_check as cc
import macro_global_gate as mgg
import signal_engine as se
import swing_lib as sl
import tune_trend as tt

pd.set_option("display.width", 250)
WINS = {"全样本": ("2024-06-01", "2026-09-11"), "2025": ("2025-01-01", "2025-12-31"),
        "2026": ("2026-01-01", "2026-09-11")}
DIP = 0.7
KEEP_COLS = ("B1_panic", "B2_crash")


def build(feat: pd.DataFrame, mkt: pd.DataFrame, g: pd.DataFrame,
          gate: str | None = None, scale: str | None = None,
          keep: tuple = KEEP_COLS) -> pd.Series:
    sig = se.sub_signals(feat)
    allow = pd.Series(False, index=feat.index)
    for c in keep:
        allow = allow | sig[c].fillna(False)
    m = mkt.reindex(feat.index).ffill()
    gg = g.reindex(feat.index).ffill()
    cond = {
        None: pd.Series(True, index=feat.index),
        "两融>0": m["mkt_margin_chg20"] > 0,
        "费半>0": gg["sox_ret20"] > 0,
    }
    if gate:
        allow = allow & cond[gate].fillna(False)
    if scale == "两融":
        mult = pd.Series(np.where(m["mkt_margin_chg20"] > 0, 1.0, 0.5), index=feat.index)
    elif scale == "费半":
        mult = pd.Series(np.where(gg["sox_ret20"] > 0, 1.0, 0.5), index=feat.index)
    else:
        mult = pd.Series(1.0, index=feat.index)

    base = tt.banded_trend(feat, buy_band=0.05, sell_band=0.05, dip=True)
    off = tt.banded_trend(feat, buy_band=0.05, sell_band=0.05, dip=False)
    p = base.to_numpy(float)
    offn = off.to_numpy(float)
    isd = (p > 0) & (np.abs(p - DIP) < 1e-6) & (offn < 1e-6)
    p[isd & ~allow.to_numpy()] = 0.0                     # 不满足条件的先手 -> 不开仓
    keep_dip = isd & allow.to_numpy()
    p[keep_dip] = DIP * mult.to_numpy()[keep_dip]        # 满足条件 -> 按状态缩放仓位
    return pd.Series(p, index=feat.index)


COMBOS = {
    "C0 精简(B1+B2)": dict(),
    "C1 精简+两融gate": dict(gate="两融>0"),
    "C2 精简+两融缩放": dict(scale="两融"),
    "C3 精简+费半gate": dict(gate="费半>0"),
    "C4 精简+费半缩放": dict(scale="费半"),
    "C5 精简+两融gate+费半缩放": dict(gate="两融>0", scale="费半"),
}


def m_(feat, pos, a, b) -> dict:
    r = sl.backtest(feat.loc[a:b], pos.loc[a:b]).metrics
    return {"收益%": r["total_return_pct"], "回撤%": r["max_drawdown_pct"],
            "Sharpe": r["sharpe"], "Calmar": r["calmar"], "交易数": r["n_trades"]}


def main() -> None:
    g = mgg.global_daily()
    mkt = am.load_market()
    idx = pd.read_csv("data/idx_cyb.csv", parse_dates=["date"]).set_index("date")["close"]
    feat = sl.add_features(sl.load_panel()).replace([np.inf, -np.inf], np.nan)

    print("=" * 118)
    print("1. 国际复材")
    print("=" * 118)
    res = {n: {w: m_(feat, build(feat, mkt, g, **kw), *WINS[w]) for w in WINS}
           for n, kw in COMBOS.items()}
    for w in WINS:
        print(f"\n--- {w} ---")
        print(pd.DataFrame({k: v[w] for k, v in res.items()}).T.round(2).to_string())
    print("\n--- 买入持有(全样本) ---")
    print(pd.DataFrame([m_(feat, pd.Series(1.0, index=feat.index), *WINS["全样本"])]).round(2).to_string(index=False))
    print("\n--- 对照: 现配置(不过滤, A|B1|B2|B3|C) 全样本 ---")
    print(pd.DataFrame([m_(feat, tt.banded_trend(feat, buy_band=0.05, sell_band=0.05, dip=True),
                           *WINS["全样本"])]).round(2).to_string(index=False))

    print("\n" + "=" * 118)
    print("2. 跨 9 只标的 (2025-01~2026-09)")
    print("=" * 118)
    rows = []
    for code, sym, name in am.SYMBOLS:
        d = cc.fetch_peer(sym)
        if d is None or len(d) < 250:
            continue
        f = sl.add_features(cc.prep(d).assign(idx_cyb=idx.reindex(d.index).ffill()))
        f = f.replace([np.inf, -np.inf], np.nan)
        a, b = "2025-01-01", "2026-09-11"
        r = {"标的": name}
        for n, kw in COMBOS.items():
            mm = m_(f, build(f, mkt, g, **kw), a, b)
            r[f"{n}|收益"] = mm["收益%"]
            r[f"{n}|Sharpe"] = mm["Sharpe"]
            r[f"{n}|交易"] = mm["交易数"]
        rows.append(r)
    t = pd.DataFrame(rows)
    base = "C0 精简(B1+B2)"
    print(f"基准 {base}: 中位收益 {t[f'{base}|收益'].median():.1f}% | 中位Sharpe "
          f"{t[f'{base}|Sharpe'].median():.2f} | 总交易 {int(t[f'{base}|交易'].sum())}")
    for n in list(COMBOS)[1:]:
        print(f"  {n:26s} 中位 {t[f'{n}|收益'].median():7.1f}% | "
              f"收益改善 {(t[f'{n}|收益']>t[f'{base}|收益']).sum()}/9 | "
              f"Sharpe改善 {(t[f'{n}|Sharpe']>t[f'{base}|Sharpe']).sum()}/9 | "
              f"总交易 {int(t[f'{n}|交易'].sum())}")
    t.to_csv("results_global_combo.csv", index=False, encoding="utf-8-sig")
    print("\n-> results_global_combo.csv")


if __name__ == "__main__":
    main()
