"""宏观 gate 终检: 用"市场活跃度/上行"过滤先手层

研究结论(修正数据缺口后):
  - 被否证: 波动率假设(p=0.226, 2025/2026 符号都不稳)。高波动 ≠ 技术失效。
  - 稳健:   "市场活跃且上行" 这一族变量 —— 创业板指成交量5/20比(p=0.010),
            指数20日涨幅(p=0.017), 沪市两融20日变化(p=0.043);
            2025 与 2026 两段同向(量比 +2.12/+2.83, 指数20日 +1.35/+1.87)。
  阈值取经济含义明确的整数(量比>1, 指数20日>0), 不用中位数(那是样本内挑的)。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import analyze_macro as am
import cross_check as cc
import signal_engine as se
import swing_lib as sl
import tune_trend as tt

pd.set_option("display.width", 240)
FULL = ("2024-06-01", "2026-09-11")
WINS = {"全样本": FULL, "2025": ("2025-01-01", "2025-12-31"),
        "2026": ("2026-01-01", "2026-09-11")}


def pos_with_gate(feat: pd.DataFrame, mkt: pd.DataFrame, keep: tuple,
                  gate: str | None) -> pd.Series:
    """趋势层固定; 先手层按 keep 选择子策略, 并按 gate 过滤。"""
    sig = se.sub_signals(feat)
    cols = {"A": "A_pullback", "B1": "B1_panic", "B2": "B2_crash",
            "B3": "B3_snapback", "C": "C_breakout"}
    allow = pd.Series(False, index=feat.index)
    for k in keep:
        allow = allow | sig[cols[k]].fillna(False)
    if gate:
        m = mkt.reindex(feat.index).ffill()
        if gate == "量比>1":
            cond = m["mkt_amt_ratio"] > 1.0
        elif gate == "指数20日>0":
            cond = m["mkt_ret20"] > 0
        elif gate == "两融20日>0":
            cond = m["mkt_margin_chg20"] > 0
        elif gate == "量比>1 且 指数20日>0":
            cond = (m["mkt_amt_ratio"] > 1.0) & (m["mkt_ret20"] > 0)
        elif gate == "量比>1 且 两融>0":
            cond = (m["mkt_amt_ratio"] > 1.0) & (m["mkt_margin_chg20"] > 0)
        else:
            raise ValueError(gate)
        allow = allow & cond.detach().fillna(False) if hasattr(cond, "detach") else allow & cond.fillna(False)

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


KEEP_FULL = ("A", "B1", "B2", "B3", "C")
KEEP_SLIM = ("B1", "B2")

CONFIGS = {
    "① 现配置": (KEEP_FULL, None),
    "② 精简(B1+B2)": (KEEP_SLIM, None),
    "③ 精简 + 量比>1": (KEEP_SLIM, "量比>1"),
    "④ 精简 + 指数20日>0": (KEEP_SLIM, "指数20日>0"),
    "⑤ 精简 + 两融20日>0": (KEEP_SLIM, "两融20日>0"),
    "⑥ 精简 + 量比>1且指数20日>0": (KEEP_SLIM, "量比>1 且 指数20日>0"),
    "⑦ 精简 + 量比>1且两融>0": (KEEP_SLIM, "量比>1 且 两融>0"),
}


def main() -> None:
    mkt = am.load_market()
    idx = pd.read_csv("data/idx_cyb.csv", parse_dates=["date"]).set_index("date")["close"]
    feat = sl.add_features(sl.load_panel()).replace([np.inf, -np.inf], np.nan)

    print("=" * 122)
    print("1. 国际复材: 各 gate 配置对比")
    print("=" * 122)
    res = {}
    for name, (keep, gate) in CONFIGS.items():
        pos = pos_with_gate(feat, mkt, keep, gate)
        res[name] = {w: st_(feat, pos, *FULL if w == "全样本" else WINS[w]) for w in WINS}
    for w in WINS:
        print(f"\n--- {w} ---")
        print(pd.DataFrame({k: v[w] for k, v in res.items()}).T.round(2).to_string())
    print("\n--- 买入持有(对照) ---")
    print(pd.DataFrame([st_(feat, pd.Series(1.0, index=feat.index), *FULL)]).round(2).to_string(index=False))

    print("\n" + "=" * 122)
    print("2. 逐月日历: 选中配置 = 精简 + 量比>1且指数20日>0   (国际复材)")
    print("=" * 122)
    bank = pos_with_gate(feat, mkt, KEEP_SLIM, "量比>1 且 指数20日>0")
    noslim = pos_with_gate(feat, mkt, KEEP_FULL, None)
    m = mkt.reindex(feat.index).ffill()
    allow_d = ((m["mkt_amt_ratio"] > 1.0) & (m["mkt_ret20"] > 0))
    cal = pd.DataFrame({
        "允许先手": allow_d.resample("ME").mean(),
        "量比": m["mkt_amt_ratio"].resample("ME").last(),
        "指数20日%": m["mkt_ret20"].resample("ME").last(),
        "本配置收益%": ((1 + sl.backtest(feat, bank).equity.pct_change().fillna(0)).resample("ME").prod() - 1) * 100,
        "原策略收益%": ((1 + sl.backtest(feat, noslim).equity.pct_change().fillna(0)).resample("ME").prod() - 1) * 100,
        "持有收益%": (feat["close"].pct_change().fillna(0).add(1).resample("ME").prod() - 1) * 100,
        "信号数": bank.diff().abs().gt(1e-9).resample("ME").sum(),
    }).loc["2025-01-01":"2026-09-30"]
    cal["gate"] = np.where(cal["允许先手"] > 0.5, "开", "关")
    cal["vs原策略"] = np.where(cal["本配置收益%"] > cal["原策略收益%"], "更好", "更差")
    cal.index = cal.index.to_period("M").astype(str)
    print(cal[["gate", "量比", "指数20日%", "本配置收益%", "原策略收益%", "持有收益%", "信号数", "vs原策略"]]
          .round(2).to_string())
    on, off = cal[cal.gate == "开"]["本配置收益%"], cal[cal.gate == "关"]["本配置收益%"]
    print(f"\ngate 开: {len(on)} 个月, 中位月收益 {on.median():+.1f}%, 胜率(vs持有) "
          f"{(cal[cal.gate=='开']['本配置收益%'] > cal[cal.gate=='开']['持有收益%']).mean()*100:.0f}%")
    print(f"gate 关: {len(off)} 个月, 中位月收益 {off.median():+.1f}%, 胜率(vs持有) "
          f"{(cal[cal.gate=='关']['本配置收益%'] > cal[cal.gate=='关']['持有收益%']).mean()*100:.0f}%")

    print("\n" + "=" * 122)
    print("3. 跨 9 只标的 (2025-01~2026-09): 现配置 vs 精简+gate")
    print("=" * 122)
    rows = []
    for code, sym, name in am.SYMBOLS:
        d = cc.fetch_peer(sym)
        if d is None or len(d) < 200:
            continue
        d = cc.prep(d).assign(idx_cyb=idx.reindex(d.index).ffill())
        f = sl.add_features(d).replace([np.inf, -np.inf], np.nan)
        a, b = "2025-01-01", "2026-09-11"
        b0 = st_(f, pos_with_gate(f, mkt, KEEP_FULL, None), a, b)
        b1 = st_(f, pos_with_gate(f, mkt, KEEP_SLIM, "量比>1 且 指数20日>0"), a, b)
        rows.append({"标的": name, "现收益%": b0["收益%"], "新收益%": b1["收益%"],
                     "现回撤%": b0["回撤%"], "新回撤%": b1["回撤%"],
                     "现Sharpe": b0["Sharpe"], "新Sharpe": b1["Sharpe"],
                     "现Calmar": b0["Calmar"], "新Calmar": b1["Calmar"],
                     "现交易": b0["交易数"], "新交易": b1["交易数"]})
    t = pd.DataFrame(rows)
    print(t.round(2).to_string(index=False))
    print(f"\n交易数: {t['现交易'].sum()} -> {t['新交易'].sum()} "
          f"(-{(1 - t['新交易'].sum() / t['现交易'].sum()) * 100:.0f}%)")
    for k in ("收益%", "回撤%", "Sharpe", "Calmar"):
        print(f"  {k:8s} 改善 {(t[f'新{k}'] > t[f'现{k}']).sum()}/9 | "
              f"中位 {t[f'现{k}'].median():.2f} -> {t[f'新{k}'].median():.2f}")
    t.to_csv("results_gate_final.csv", index=False, encoding="utf-8-sig")
    cal.to_csv("results_gate_calendar.csv", encoding="utf-8-sig")
    print("\n-> results_gate_final.csv / results_gate_calendar.csv")


if __name__ == "__main__":
    main()
