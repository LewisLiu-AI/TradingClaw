"""信号研究: 哪些特征在样本内(2025)真正区分波段底/顶?

输出:
  1. 每个特征对 "未来3日内出现波段底/顶" 的 AUC(样本内/样本外分别算)
  2. 候选信号的历史条件收益(信号后 5/10/20 日收益分布)
  3. 顶部派发类硬数据(融资余额/大宗折价)的条件统计

注意: 这里只做"研究", 结论要经过策略回测才算数。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

import swing_lib as sl

pd.set_option("display.width", 220)
IS_END = "2025-12-31"
OOS_START = "2026-01-01"
ZIGZAG = 0.12
TOL_BACK, TOL_FWD = 2, 3      # 信号落在 [pivot-2, pivot+3] 视为命中


def build() -> tuple[pd.DataFrame, pd.DataFrame]:
    px = sl.load_panel()
    df = sl.add_features(px)
    _, piv = sl.pivot_frame(df, ZIGZAG)
    lab = pd.DataFrame(0, index=df.index, columns=["near_bottom", "near_top"])
    for _, p in piv.iterrows():
        lo = max(0, p["idx"] - TOL_BACK)
        hi = min(len(df) - 1, p["idx"] + TOL_FWD)
        col = "near_bottom" if p["kind"] == "bottom" else "near_top"
        lab.iloc[lo:hi + 1, lab.columns.get_loc(col)] = 1
    # 前瞻收益(研究用, 不进策略)
    for k in (5, 10, 20):
        df[f"fwd{k}"] = df["close"].shift(-k) / df["close"] - 1
    df["fwd10_nolook"] = df["close"].shift(-10) / df["open"].shift(-1) - 1
    return df, pd.concat([lab, piv.assign(idx=piv["idx"])], axis=0) if False else (df, piv)


FEATURES = [
    "ret1", "ret5", "ret10", "ret20", "ret60",
    "dist_ma5", "dist_ma10", "dist_ma20", "dist_ma30", "dist_ma60", "dist_ma120",
    "ma20_slope", "ma60_slope", "ma_align", "rsi2", "rsi14", "rsi14_prev3",
    "atr_pct", "amp", "bb_z", "bb_width",
    "dd_high20", "dd_high60", "dd_high120", "up_low20", "up_low60", "up_low120",
    "new_high20", "new_low20", "vol_ratio", "vol_ratio5", "vol_z",
    "turnover", "turn_dist", "body_pct", "upper_shadow", "lower_shadow", "close_pos",
    "gap", "down_streak", "up_streak",
    "idx_cyb_ret5", "idx_cyb_ret20", "idx_cyb_dd60", "rs_cyb_20", "beta60_cyb",
    "idx_hs300_ret20", "rs_hs300_20",
    "rz_chg5", "rz_chg20", "rz_z20", "rz_net5", "rz_net5_intensity", "rz_level", "rq_chg20",
    "main_net5", "main_net10", "main_pct5",
    "block_amt20", "block_amt20_pct", "block_flag20", "block_premium20",
    "lhb_net20", "holders_chg", "inst_part_chg20",
]


def auc_table(df: pd.DataFrame, piv: pd.DataFrame) -> pd.DataFrame:
    def score(mask: pd.Series, name: str) -> pd.DataFrame:
        rows = []
        is_m = df.index <= pd.Timestamp(IS_END)
        oos_m = df.index >= pd.Timestamp(OOS_START)
        for f in FEATURES:
            if f not in df.columns:
                continue
            x = df[f]
            ok = x.notna()
            if ok.sum() < 40:
                continue
            y_is, x_is = mask[ok & is_m], x[ok & is_m]
            y_oos, x_oos = mask[ok & oos_m], x[ok & oos_m]
            if y_is.nunique() < 2 or y_oos.nunique() < 2:
                continue
            try:
                a_is = roc_auc_score(y_is, x_is)
                a_oos = roc_auc_score(y_oos, x_oos)
            except Exception as exc:  # noqa: BLE001
                print(f"  skip {f}: {exc}")
                continue
            rows.append({"feature": f, "auc_IS": a_is, "auc_OOS": a_oos,
                         "n_sig": int(mask[ok].sum()),
                         "mean_in": x[ok][mask[ok] == 1].mean(),
                         "mean_out": x[ok][mask[ok] == 0].mean()})
        t = pd.DataFrame(rows)
        if t.empty:
            print(f"{name}: 无有效特征")
            return t
        t["auc_edge_is"] = (t["auc_IS"] - 0.5).abs()
        t["auc_edge_oos"] = (t["auc_OOS"] - 0.5).abs()
        t = t.sort_values("auc_edge_is", ascending=False)
        print(f"\n=== {name}: 区分度 TOP15 (按样本内 AUC 偏离) ===")
        print(t.head(15).round(3).to_string(index=False))
        print(f"--- 样本内外同向且都>0.60 的特征 ---")
        same = t[(t.auc_edge_is > 0.10) & (t.auc_edge_oos > 0.10) &
                 (np.sign(t.auc_IS - 0.5) == np.sign(t.auc_OOS - 0.5))]
        print(same[["feature", "auc_IS", "auc_OOS", "mean_in", "mean_out"]].round(3).to_string(index=False))
        return t
    return score


def main() -> None:
    px = sl.load_panel()
    df = sl.add_features(px).replace([np.inf, -np.inf], np.nan)
    for k in (3, 5, 10, 20, 40):
        df[f"fwd{k}"] = df["close"].shift(-k) / df["close"] - 1
    _, piv = sl.pivot_frame(df, ZIGZAG)
    lab = pd.DataFrame(0, index=df.index, columns=["near_bottom", "near_top"])
    for _, p in piv.iterrows():
        lo, hi = max(0, p["idx"] - TOL_BACK), min(len(df) - 1, p["idx"] + TOL_FWD)
        col = "near_bottom" if p["kind"] == "bottom" else "near_top"
        lab.iloc[lo:hi + 1, lab.columns.get_loc(col)] = 1

    study = df.loc["2025-01-01":]
    print(f"研究窗口 {study.index.min().date()} .. {study.index.max().date()}  ({len(study)} bars)")
    print(f"底部命中窗口 {int(lab.loc['2025-01-01':,'near_bottom'].sum())} 天, "
          f"顶部命中窗口 {int(lab.loc['2025-01-01':,'near_top'].sum())} 天, "
          f"pivots={len(piv[piv.date>='2025-01-01'])}")

    scorer = auc_table(df, piv)
    scorer(lab["near_bottom"], "波段底 (near_bottom)")
    scorer(lab["near_top"], "波段顶 (near_top)")

    # ── 条件收益: 单特征分位 vs 未来10日收益 ──
    print("\n\n=== 单特征分位 -> 未来10日收益(仅样本内 2025) ===")
    is_df = df.loc["2025-01-01":IS_END]
    for f in ("rsi2", "rsi14", "dd_high60", "dist_ma20", "vol_ratio", "turn_dist",
              "up_low60", "rz_chg20", "rz_z20", "block_amt20_pct", "bb_z"):
        if f not in is_df.columns:
            continue
        x, y = is_df[f], is_df["fwd10"]
        ok = x.notna() & y.notna()
        if ok.sum() < 50:
            continue
        try:
            q = pd.qcut(x[ok], 5, labels=False, duplicates="drop")
        except Exception:  # noqa: BLE001
            continue
        g = y[ok].groupby(q).agg(["mean", "count"])
        g.index = [f"Q{i+1}" for i in g.index]
        print(f"{f:22s} " + "  ".join(f"{i}:{r['mean']*100:+6.1f}%" for i, r in g.iterrows()))

    # ── 顶部派发硬数据 ──
    print("\n=== 大宗折价减持 / 融资杠杆 的顶部条件统计 ===")
    tops = piv[piv.kind == "top"].set_index("date")
    for f in ("block_amt20_pct", "rz_chg20", "rz_z20", "turn_dist", "up_low60", "dist_ma20"):
        x = df[f].reindex(tops.index)
        print(f"{f:20s} 顶部时均值 {x.mean():+9.2f} | 全样本均值 {df[f].mean():+9.2f}")

    piv.to_csv("data/_pivots_zigzag12.csv", index=False)


if __name__ == "__main__":
    main()
