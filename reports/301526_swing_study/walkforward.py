"""走查验证 — 统一使用「推荐配置」(= signal_engine 的默认参数)

推荐配置:
  核心 L1+L2 趋势滞回带: 收盘>MA20×1.05 且 MA20>MA60 建仓;
                          收盘<MA20×0.95 或 MA20<MA60 离场; 中间地带维持。
  L3 抄底先手(仅空仓时): B1/B2/B3 → 0.7 仓。
  L4 顶部减仓: 默认关闭(见 REPORT 第 4.3 节: 会让全样本收益 823%→446%)。

用法:
    python walkforward.py            # 全部
    python walkforward.py --quick    # 跳过敏感性网格
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

import signal_engine as se
import strategy as st
import swing_lib as sl
import tune_trend as tt

pd.set_option("display.width", 220)

IS = ("2025-01-01", "2025-12-31")
OOS = ("2026-01-01", "2026-09-11")
FULL = ("2024-06-01", "2026-09-11")
CORE = dict(buy_band=0.05, sell_band=0.05)
RECOMMENDED = dict(buy_band=0.05, sell_band=0.05, dip=True)

KEYS = ("total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "calmar",
        "n_trades", "win_rate_pct", "profit_factor", "avg_hold_days", "exposure_pct")


def load() -> pd.DataFrame:
    return sl.add_features(sl.load_panel()).replace([np.inf, -np.inf], np.nan)


def summarize(m: dict) -> dict:
    return {k: m.get(k) for k in KEYS}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    df = load()
    out = {}

    print("#" * 92)
    print("# 1. 分窗口表现: 推荐配置 / 纯核心 / 买入持有")
    print("#" * 92)
    for label, (a, b) in (("样本内 IS (2025)", IS), ("样本外 OOS (2026)", OOS),
                          ("全样本", FULL)):
        sub = df.loc[a:b]
        rows = []
        for name, pos in (("买入持有", pd.Series(1.0, index=df.index)),
                          ("纯核心(滞回带5%/5%)", tt.banded_trend(df, **CORE)),
                          ("推荐(核心+抄底先手)", tt.banded_trend(df, **RECOMMENDED))):
            m = sl.backtest(sub, pos.reindex(sub.index)).metrics
            rows.append({"配置": name, "收益%": m["total_return_pct"],
                         "年化%": m["cagr_pct"], "回撤%": m["max_drawdown_pct"],
                         "Sharpe": m["sharpe"], "Calmar": m["calmar"],
                         "交易数": m["n_trades"], "胜率%": m["win_rate_pct"],
                         "盈亏比": m["profit_factor"], "在场%": m["exposure_pct"]})
            out[f"{label}|{name}"] = summarize(m)
        print(f"\n--- {label} ({sub.index.min().date()} ~ {sub.index.max().date()}) ---")
        print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n" + "#" * 92)
    print("# 2. 顶底检测命中率 (ZigZag 12% 真值, 命中窗口 -2/+3 天)")
    print("#" * 92)
    sig = se.sub_signals(df)
    det = st.evaluate_detection(df, sig)
    for k, v in det.items():
        nm = "波段底" if k == "bottom" else "波段顶"
        print(f"{nm}: 真值 {v['n_pivots']} 个 | 召回 {v['recall_pct']:.0f}% | "
              f"信号 {v['n_signal_days']} 天 | 精确率 {v['precision_pct']:.0f}% | "
              f"漏检: {v['missed']}")
        out[f"detection_{k}"] = {**{kk: vv for kk, vv in v.items() if kk != 'missed'},
                                 "missed": [str(d) for d in v["missed"]]}

    print("\n" + "#" * 92)
    print("# 3. 分段稳健性 (全样本切 6 段)")
    print("#" * 92)
    pos = tt.banded_trend(df, **RECOMMENDED)
    sub = df.loc[FULL[0]:FULL[1]]
    edges = pd.date_range(sub.index.min(), sub.index.max(), periods=7)
    rows = []
    for i in range(6):
        seg = sub.loc[edges[i]:edges[i + 1]]
        if len(seg) < 20:
            continue
        s = sl.backtest(seg, pos).metrics
        b = sl.backtest(seg, pd.Series(1.0, index=seg.index)).metrics
        rows.append({"区间": f"{seg.index.min().date()}~{seg.index.max().date()}",
                     "策略%": s["total_return_pct"], "持有%": b["total_return_pct"],
                     "超额%": s["total_return_pct"] - b["total_return_pct"],
                     "策略回撤%": s["max_drawdown_pct"], "持有回撤%": b["max_drawdown_pct"]})
    rw = pd.DataFrame(rows)
    print(rw.round(1).to_string(index=False))
    out["rolling"] = rw.to_dict("records")

    if not args.quick:
        print("\n" + "#" * 92)
        print("# 4. 参数敏感性 (±20%, 全样本)")
        print("#" * 92)
        p = st.Params()
        base = sl.backtest(sub, pos).metrics
        rows = [{"param": "BASE", "ret%": base["total_return_pct"],
                 "mdd%": base["max_drawdown_pct"], "calmar": base["calmar"]}]
        import dataclasses
        for f in (fd.name for fd in dataclasses.fields(p)):
            cur = getattr(p, f)
            if not isinstance(cur, (int, float)) or isinstance(cur, bool):
                continue
            for mult in (0.8, 1.2):
                setattr(p, f, cur * mult if cur else 0.05 * mult)
                m = sl.backtest(sub, tt.banded_trend(df, p=p, **RECOMMENDED)).metrics
                rows.append({"param": f"{f}x{mult}", "ret%": m["total_return_pct"],
                             "mdd%": m["max_drawdown_pct"], "calmar": m["calmar"]})
                setattr(p, f, cur)
        t = pd.DataFrame(rows)
        t["d_ret"] = t["ret%"] - t.iloc[0]["ret%"]
        t["d_calmar"] = t["calmar"] - t.iloc[0]["calmar"]
        print(t.round(2).to_string(index=False))
        print(f"\n敏感度: d收益 标准差 {t['d_ret'].std():.1f}pp | "
              f"dCalmar 标准差 {t['d_calmar'].std():.2f} | 最差 dCalmar {t['d_calmar'].min():.2f}")
        out["sensitivity"] = t.to_dict("records")

    res = sl.backtest(sub, pos)
    res.equity.to_csv("results_equity_full.csv")
    res.positions.to_csv("results_position_full.csv")
    pd.DataFrame([res.metrics]).to_csv("results_metrics_full.csv", index=False)
    with open("results_summary.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\n结果已落盘: results_summary.json / results_equity_full.csv / results_metrics_full.csv")


if __name__ == "__main__":
    main()
