"""市场状态 gate 的统计检验 + 加到整个策略上的效果。

要点:
  1. 先手贡献的截面/时序波动极大(n=189, 尾部 ±20%+), 必须做显著性检验, 否则容易把噪声当信号。
  2. 除了"只 gate 先手层", 还要测"gate 整个策略"(市场择时开关)。
  3. 用 2025 选 gate、2026 验证, 检查是否样本内挑出来的。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import analyze_macro as am
import signal_engine as se
import swing_lib as sl
import tune_trend as tt

pd.set_option("display.width", 240)
RNG = np.random.default_rng(42)


def bootstrap_diff(hi: np.ndarray, lo: np.ndarray, n: int = 5000) -> dict:
    """两组均值差的 bootstrap 置信区间与经验 p 值(单尾: hi > lo)。"""
    obs = hi.mean() - lo.mean()
    pool = np.concatenate([hi, lo])
    cnt = 0
    for _ in range(n):
        s = RNG.permutation(pool)
        cnt += (s[:len(hi)].mean() - s[len(hi):].mean()) >= obs
    return {"diff": obs, "p_one_sided": cnt / n, "n_hi": len(hi), "n_lo": len(lo)}


def main() -> None:
    panel = pd.read_csv("results_macro_panel.csv")
    print("=" * 120)
    print("1. 市场变量分组差异的显著性检验(bootstrap 置换, 5000 次)")
    print("=" * 120)
    rows = []
    for f in am.MKT_FEATS:
        if f not in panel.columns:
            continue
        x, y = panel[f].astype(float), panel["先手贡献%"]
        ok = x.notna() & y.notna()
        if ok.sum() < 100 or x[ok].nunique() < 3:
            continue
        med = x[ok].median()
        hi, lo = y[ok][x[ok] > med].to_numpy(), y[ok][x[ok] <= med].to_numpy()
        b = bootstrap_diff(hi, lo)
        rows.append({"市场变量": f, "高组均值%": hi.mean(), "低组均值%": lo.mean(),
                     "差异pp": b["diff"], "p值(单尾)": b["p_one_sided"],
                     "显著(p<0.05)": "是" if b["p_one_sided"] < 0.05 else "否"})
    t = pd.DataFrame(rows).sort_values("p值(单尾)")
    print(t.round(3).to_string(index=False))
    print(f"\n注: 共检验 {len(t)} 个变量; 若无多重检验校正, 期望有 {len(t)*0.05:.1f} 个"
          f"变量仅凭偶然就能达到 p<0.05。")

    print("\n" + "=" * 120)
    print("2. 用 2025 选 gate, 2026 验证(避免样本内挑选)")
    print("=" * 120)
    p25 = panel[panel["月份"] <= "2025-12"]
    p26 = panel[panel["月份"] >= "2026-01"]
    rows = []
    for f in ["mkt_above_ma20", "mkt_ma20_gt_ma60", "mkt_vol20", "mkt_ret20",
              "mkt_margin_chg20", "mkt_amt_ratio"]:
        if f not in panel.columns:
            continue
        for lab, sub in (("2025(选)", p25), ("2026(验)", p26)):
            x, y = sub[f].astype(float), sub["先手贡献%"]
            ok = x.notna() & y.notna()
            if ok.sum() < 50 or x[ok].nunique() < 2:
                continue
            med = x[ok].median()
            rows.append({"变量": f, "窗口": lab,
                         "高组均值%": y[ok][x[ok] > med].mean(),
                         "低组均值%": y[ok][x[ok] <= med].mean(),
                         "差异pp": y[ok][x[ok] > med].mean() - y[ok][x[ok] <= med].mean()})
    t2 = pd.DataFrame(rows)
    piv = t2.pivot_table(index="变量", columns="窗口", values="差异pp").round(3)
    print(piv.to_string())
    print("\n若 2025 与 2026 的差异符号相反 -> 该变量在两个时期不稳定, 不能当 gate。")

    print("\n" + "=" * 120)
    print("3. 把市场 gate 加到**整个策略**(不只先手层): 国际复材")
    print("=" * 120)
    feat = sl.add_features(sl.load_panel()).replace([np.inf, -np.inf], np.nan)
    mkt = am.load_market().reindex(feat.index).ffill()
    base = tt.banded_trend(feat, buy_band=0.05, sell_band=0.05, dip=True)
    base_off = tt.banded_trend(feat, buy_band=0.05, sell_band=0.05, dip=False)
    wins = {"2024-06~2026-09": ("2024-06-01", "2026-09-11"),
            "2025": ("2025-01-01", "2025-12-31"),
            "2026": ("2026-01-01", "2026-09-11")}

    def run(pos: pd.Series) -> None:
        for lab, (a, b) in wins.items():
            m = sl.backtest(feat.loc[a:b], pos.loc[a:b]).metrics
            print(f"       {lab:16s} 收益 {m['total_return_pct']:7.1f}% | 回撤 {m['max_drawdown_pct']:6.1f}% | "
                  f"Sharpe {m['sharpe']:.2f} | 交易 {m['n_trades']:2d}")

    print("\n  [A] 基准: 推荐配置(不择时)")
    run(base)
    print("\n  [B] 只 gate 先手层: 指数在MA20上方才允许先手")
    allow = (mkt["mkt_above_ma20"] == 1).reindex(feat.index).fillna(False)
    p = base.to_numpy(float).copy(); off = base_off.to_numpy(float)
    is_dip = (p > 0) & (np.abs(p - 0.7) < 1e-6) & (off < 1e-6)
    p[is_dip & ~allow.to_numpy()] = 0.0
    run(pd.Series(p, index=feat.index))
    print("\n  [C] 整个策略空仓: 指数在MA20下方时一律空仓")
    run(base.where(allow, 0.0))
    print("\n  [D] 整个策略降半仓: 指数在MA20下方时 ×0.5")
    run(base.where(allow, base * 0.5))
    print("\n  [E] 整个策略空仓: 指数MA20<MA60 时一律空仓")
    allow2 = (mkt["mkt_ma20_gt_ma60"] == 1).reindex(feat.index).fillna(False)
    run(base.where(allow2, 0.0))
    print("\n  [F] 买入持有(对照)")
    run(pd.Series(1.0, index=feat.index))


if __name__ == "__main__":
    main()
