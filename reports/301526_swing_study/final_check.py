"""终检: 置换检验 / 参数敏感性 / 滚动分段 / 交易明细

置换检验(block permutation)回答一个关键问题:
  策略的收益是来自择时能力, 还是仅仅来自"碰巧在上涨的那几天在场"?
做法: 保持持仓天数与持仓段长度分布不变, 把持仓段整体随机平移(块置换),
      重复 1000 次得到收益分布; 看真实收益处于什么分位。
"""
from __future__ import annotations

import dataclasses
import json

import numpy as np
import pandas as pd

import swing_lib as sl
import strategy as st
import tune_trend as tt

FULL = ("2024-06-01", "2026-09-11")
IS = ("2025-01-01", "2025-12-31")
OOS = ("2026-01-01", "2026-09-11")
FINAL = dict(buy_band=0.05, sell_band=0.05, dip=True)
CORE = dict(buy_band=0.05, sell_band=0.05)


def block_permutation(df: pd.DataFrame, pos: pd.Series, n: int = 1000,
                      seed: int = 7) -> dict:
    """把持仓段(连续>0的块)整体循环平移, 保持块长度与数量。"""
    p = pos.reindex(df.index).fillna(0.0).to_numpy(float)
    n_bar = len(p)
    # 找出持仓块
    blocks, i = [], 0
    while i < n_bar:
        if p[i] > 0:
            j = i
            while j + 1 < n_bar and p[j + 1] > 0:
                j += 1
            blocks.append((i, j - i + 1))
            i = j + 1
        else:
            i += 1
    rng = np.random.default_rng(seed)
    rets = df["close"].pct_change().fillna(0.0).to_numpy(float)
    real = sl.backtest(df, pos).metrics["total_return_pct"]
    sims = []
    for _ in range(n):
        q = np.zeros(n_bar)
        for _, ln in blocks:
            start = int(rng.integers(0, n_bar))
            for k in range(ln):
                q[(start + k) % n_bar] = 1.0
        sims.append(sl.backtest(df, pd.Series(q, index=df.index)).metrics["total_return_pct"])
    sims = np.array(sims)
    return {"real_return_pct": real, "perm_mean_pct": float(sims.mean()),
            "perm_p05": float(np.percentile(sims, 5)),
            "perm_p50": float(np.percentile(sims, 50)),
            "perm_p95": float(np.percentile(sims, 95)),
            "pctile_of_real": float((sims < real).mean() * 100), "n": n}


def rolling(df: pd.DataFrame, pos: pd.Series, n: int = 6) -> pd.DataFrame:
    sub = df.loc[FULL[0]:FULL[1]]
    edges = pd.date_range(sub.index.min(), sub.index.max(), periods=n + 1)
    rows = []
    for i in range(n):
        seg = sub.loc[edges[i]:edges[i + 1]]
        if len(seg) < 20:
            continue
        s = sl.backtest(seg, pos).metrics
        b = sl.backtest(seg, pd.Series(1.0, index=seg.index)).metrics
        rows.append({"区间": f"{seg.index.min().date()}~{seg.index.max().date()}",
                     "策略%": s["total_return_pct"], "持有%": b["total_return_pct"],
                     "超额%": s["total_return_pct"] - b["total_return_pct"],
                     "策略回撤%": s["max_drawdown_pct"], "持有回撤%": b["max_drawdown_pct"]})
    return pd.DataFrame(rows)


def main() -> None:
    df = sl.add_features(sl.load_panel()).replace([np.inf, -np.inf], np.nan)
    out = {}

    print("=" * 100)
    print("1. 最终配置在 国际复材 上的表现")
    print("=" * 100)
    cfgs = {
        "核心:趋势滞回带(5%/5%)": CORE,
        "推荐:核心+抄底先手": FINAL,
    }
    for name, kw in cfgs.items():
        print(f"\n--- {name} ---")
        pos = tt.banded_trend(df, **kw)
        for lab, (a, b) in (("IS 2025", IS), ("OOS 2026", OOS), ("全样本", FULL)):
            m = sl.backtest(df.loc[a:b], pos).metrics
            bh = sl.backtest(df.loc[a:b], pd.Series(1.0, index=df.loc[a:b].index)).metrics
            print(f"{lab:>10}: 策略 {m['total_return_pct']:8.1f}% / 回撤 {m['max_drawdown_pct']:7.1f}% / "
                  f"Sharpe {m['sharpe']:.2f} / Calmar {m['calmar']:5.2f} | "
                  f"持有 {bh['total_return_pct']:8.1f}% / {bh['max_drawdown_pct']:7.1f}%")
            out[f"{name}|{lab}"] = {"strategy": m, "buy_hold": bh}

    print("\n" + "=" * 100)
    print("2. 置换检验: 随机平移持仓块 1000 次")
    print("=" * 100)
    pos_final = tt.banded_trend(df, **FINAL)
    perm = block_permutation(df.loc[FULL[0]:FULL[1]], pos_final.loc[FULL[0]:FULL[1]])
    print(f"真实收益 {perm['real_return_pct']:.1f}% | 置换分布 5% {perm['perm_p05']:.1f}% / "
          f"中位 {perm['perm_p50']:.1f}% / 95% {perm['perm_p95']:.1f}%")
    print(f"真实收益位于置换分布的第 {perm['pctile_of_real']:.1f} 百分位")
    out["permutation"] = perm

    print("\n" + "=" * 100)
    print("3. 分段稳健性 (全样本切 6 段)")
    print("=" * 100)
    r = rolling(df, pos_final)
    print(r.round(1).to_string(index=False))
    out["rolling"] = r.to_dict("records")

    print("\n" + "=" * 100)
    print("4. 参数敏感性 (每个参数 ±20%, 全样本, 推荐配置)")
    print("=" * 100)
    p = st.Params()
    base = sl.backtest(df.loc[FULL[0]:FULL[1]], pos_final).metrics
    rows = [{"param": "BASE", "ret%": base["total_return_pct"],
             "mdd%": base["max_drawdown_pct"], "calmar": base["calmar"]}]
    for f in (fd.name for fd in dataclasses.fields(p)):
        cur = getattr(p, f)
        if not isinstance(cur, (int, float)) or isinstance(cur, bool):
            continue
        for mult in (0.8, 1.2):
            setattr(p, f, cur * mult if cur else 0.05 * mult)
            m = sl.backtest(df.loc[FULL[0]:FULL[1]], tt.banded_trend(df, p=p, **FINAL)).metrics
            rows.append({"param": f"{f}×{mult}", "ret%": m["total_return_pct"],
                         "mdd%": m["max_drawdown_pct"], "calmar": m["calmar"]})
            setattr(p, f, cur)
    t = pd.DataFrame(rows)
    t["Δret"] = t["ret%"] - t.iloc[0]["ret%"]
    t["Δcalmar"] = t["calmar"] - t.iloc[0]["calmar"]
    print(t.round(2).to_string(index=False))
    print(f"\n敏感度: Δ收益 标准差 {t['Δret'].std():.1f}pp | ΔCalmar 标准差 {t['Δcalmar'].std():.2f} "
          f"| 最差 ΔCalmar {t['Δcalmar'].min():.2f}")
    out["sensitivity"] = t.to_dict("records")

    print("\n" + "=" * 100)
    print("5. 交易明细 (推荐配置, 全样本)")
    print("=" * 100)
    res = sl.backtest(df.loc[FULL[0]:FULL[1]], pos_final)
    trades = pd.DataFrame([{"进": t_.entry_date.date(), "出": t_.exit_date.date(),
                            "进价": round(t_.entry_px, 2), "出价": round(t_.exit_px, 2),
                            "收益%": round(t_.ret * 100, 1), "持有天": t_.hold_days}
                           for t_ in res.trades])
    print(trades.to_string(index=False))
    out["trades"] = trades.to_dict("records")

    res.equity.to_csv("results_equity_final.csv")
    pos_final.to_csv("results_position_final.csv")
    with open("results_final_check.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\n-> results_final_check.json / results_equity_final.csv")


if __name__ == "__main__":
    main()
