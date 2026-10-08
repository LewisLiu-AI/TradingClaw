"""国际复材(301526.SZ) 波段策略 — 自包含信号引擎

自包含(不依赖 swing_lib), 可直接被仓库回测框架调用:
    run_dir/config.json + run_dir/code/signal_engine.py
    python -m backtest.runner <run_dir>

策略结构(见 REPORT.md 的论证):
  核心 L1+L2 : 趋势滞回带 —— 收盘>MA20*(1+buy_band) 且 MA20>MA60 建仓;
               收盘<MA20*(1-sell_band) 或 MA20<MA60 离场; 中间地带维持原状态。
  L3 抄底先手: 空仓时, 由 B1/B2/B3 三类底部形态先手建小仓。
  L4 顶部减仓: (默认关闭) 过热/杠杆极端/大宗派发时减仓 —— 回测显示会显著牺牲收益,
               仅在明确要压回撤或使用杠杆时启用。

输出: Dict[str, pd.Series] — 目标仓位(0~1), t 日收盘生成, t+1 开盘成交。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


# ────────────────────────────── 参数 ──────────────────────────────
# 注: 写成函数而非模块级常量 —— 仓库回测框架的 AST 安全门只允许字面量赋值,
# 而 "负数常量" 在 AST 中是 UnaryOp, 会被判定为可执行语句。
def default_params() -> dict:
    return {
        # 核心 L1+L2
        "ma_fast": 20,
        "ma_slow": 60,
        "buy_band": 0.05,      # 进场需高于 MA20 的幅度(滞回带)
        "sell_band": 0.05,     # 跌破 MA20 的容忍度(滞回带, 抗震荡的关键)
        # L3 抄底先手
        "dip_size": 0.7,       # 先手仓位
        "dd20_panic": -13.0,   # 系统性恐慌: 距20日高点回撤
        "ret5_panic": -6.0,
        "idx5_panic": -1.5,
        "atr_panic": 4.0,
        "dd20_crash": -35.0,   # 个股崩跌
        "ret5_crash": -10.0,
        "rsi_crash": 45.0,
        "ret3_snap": -10.0,    # 强势股急回踩
        "dist20_snap": -3.0,
        # L4 减仓(默认关闭)
        "enable_derisk": False,
        "derisk_trim": 0.5,
        "dist20_hot": 18.0,
        "uplow20_hot": 40.0,
        "rz_z_hot": 2.0,
        "turn_hot": 12.0,
        "block_pct_hot": 0.25,
        "slope_break": -0.3,
    }


def _rsi(s: pd.Series, n: int) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50.0)


def _data_dir() -> Path:
    here = Path(__file__).resolve().parent
    for cand in (here.parent.parent / "data", here.parent / "data", here / "data"):
        if (cand / "px_qfq.csv").exists():
            return cand
    return Path("data")


def build_features() -> pd.DataFrame:
    """从本地 CSV 构建因果特征(与 swing_lib.add_features 同口径, 自包含实现)。"""
    d = _data_dir()
    px = pd.read_csv(d / "px_qfq.csv", parse_dates=["date"]).set_index("date").sort_index()
    px = px[~px.index.duplicated(keep="last")]
    if px["turnover"].max() < 1.5:
        px["turnover"] = px["turnover"] * 100
    for f, col in (("idx_cyb.csv", "idx_cyb"), ("margin.csv", "margin")):
        p = d / f
        if p.exists():
            other = pd.read_csv(p, parse_dates=["date"]).set_index("date").sort_index()
            if col == "idx_cyb":
                px["idx_cyb"] = other["close"].reindex(px.index).ffill()
            else:
                for c in ("rz_balance", "rz_net", "float_mktcap"):
                    if c in other.columns:
                        px[c] = other[c].reindex(px.index).ffill()
    p = d / "block_trade.csv"
    if p.exists():
        bt = pd.read_csv(p, parse_dates=["date"])
        px["block_amount"] = bt.groupby("date")["amount"].sum().reindex(px.index).fillna(0.0)

    df = px.copy()
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    for n in (3, 5):
        df[f"ret{n}"] = c.pct_change(n) * 100
    for n in (default_params()["ma_fast"], default_params()["ma_slow"], 120):
        df[f"ma{n}"] = c.rolling(n).mean()
    df["dist_ma20"] = (c / df["ma20"] - 1) * 100
    df["ma20_slope"] = (df["ma20"] - df["ma20"].shift(10)) / df["ma20"].shift(10).abs() / 10 * 100
    df["rsi14"] = _rsi(c, 14)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    df["atr_pct"] = tr.ewm(alpha=1 / 14, adjust=False).mean() / c * 100
    df["dd_high20"] = (c / h.rolling(20).max() - 1) * 100
    df["up_low20"] = (c / l.rolling(20).min() - 1) * 100
    df["new_high20"] = (c > c.rolling(20).max().shift(1)).astype(int)
    df["vol_ratio"] = v / v.rolling(20).mean()
    if "idx_cyb" in df.columns:
        df["idx_cyb_ret5"] = df["idx_cyb"].pct_change(5) * 100
        df["idx_cyb_dd60"] = (df["idx_cyb"] / df["idx_cyb"].rolling(60).max() - 1) * 100
    if "rz_balance" in df.columns:
        rz = df["rz_balance"].shift(1)                     # 交易所晚间披露, 保守滞后
        df["rz_z20"] = (rz - rz.rolling(120).mean()) / rz.rolling(120).std()
    if "block_amount" in df.columns and "float_mktcap" in df.columns:
        ba = df["block_amount"].shift(1).fillna(0.0).rolling(20).sum()
        df["block_amt20_pct"] = ba / df["float_mktcap"].shift(1) * 100
    return df.replace([np.inf, -np.inf], np.nan)


def _c(df: pd.DataFrame, name: str, default=0.0) -> pd.Series:
    return df[name] if name in df.columns else pd.Series(default, index=df.index, dtype=float)


def sub_signals(df: pd.DataFrame, p: dict | None = None) -> pd.DataFrame:
    p = {**default_params(), **(p or {})}
    out = pd.DataFrame(index=df.index)
    trend = (df["ma20"] > df["ma60"]) & (df["ma20_slope"] > 0)
    idx_weak = df["idx_cyb_ret5"] < p["idx5_panic"] if "idx_cyb_ret5" in df.columns else True
    idx_ok = df["idx_cyb_dd60"] > -8.0 if "idx_cyb_dd60" in df.columns else True

    # L3 抄底先手(A/B/C 三类底部形态)
    out["B1_panic"] = ((df["dd_high20"] < p["dd20_panic"]) & (df["ret5"] < p["ret5_panic"])
                       & idx_weak & (df["atr_pct"] > p["atr_panic"]))
    out["B2_crash"] = ((df["dd_high20"] < p["dd20_crash"]) & (df["ret5"] < p["ret5_crash"])
                       & (df["rsi14"] < p["rsi_crash"]))
    out["B3_snapback"] = (trend & (df["ret3"] < p["ret3_snap"])
                          & (df["dist_ma20"] > p["dist20_snap"]))
    out["A_pullback"] = (trend & df["dist_ma20"].between(-8.0, 10.0)
                         & (df["vol_ratio"] < 1.1) & df["rsi14"].between(35.0, 75.0))
    out["C_breakout"] = ((df["new_high20"] == 1) & (df["vol_ratio"] > 1.3)
                         & (df["dist_ma20"] < 15.0) & idx_ok)

    # L4 顶部减仓证据
    out["D_overheat"] = (df["dist_ma20"] > p["dist20_hot"]) & (df["up_low20"] > p["uplow20_hot"])
    out["D_leverage"] = (_c(df, "rz_z20", -9) > p["rz_z_hot"]) & (df["turnover"] > p["turn_hot"])
    out["D_distribute"] = _c(df, "block_amt20_pct", -9) > p["block_pct_hot"]
    out["D_breakdown"] = (df["close"] < df["ma20"]) & (df["ma20_slope"] < p["slope_break"])
    out["n_derisk"] = out[["D_overheat", "D_leverage", "D_distribute"]].fillna(False).sum(axis=1)
    out["entry"] = out[["B1_panic", "B2_crash", "B3_snapback", "A_pullback",
                        "C_breakout"]].fillna(False).any(axis=1)
    return out


def generate_target(df: pd.DataFrame, p: dict | None = None,
                    with_derisk: bool | None = None) -> pd.Series:
    """状态机 -> 目标仓位序列。"""
    p = {**default_params(), **(p or {})}
    with_derisk = p["enable_derisk"] if with_derisk is None else with_derisk
    sig = sub_signals(df, p)
    c, ma20, ma60 = df["close"], df["ma20"], df["ma60"]
    up = (c > ma20 * (1 + p["buy_band"])) & (ma20 > ma60)
    dn = (c < ma20 * (1 - p["sell_band"])) | (ma20 < ma60)
    cn = c.to_numpy(float)
    upv, dnv = up.to_numpy(bool), dn.to_numpy(bool)
    dip = sig["entry"].fillna(False).to_numpy()
    nd = sig["n_derisk"].fillna(0).to_numpy()
    dist = sig["D_distribute"].fillna(False).to_numpy()

    out = np.zeros(len(df))
    in_pos = False
    for i in range(len(df)):
        if in_pos:
            if dnv[i]:
                in_pos = False
                continue
            w = 1.0
            if with_derisk:
                w *= (1.0 - 0.5 * p["derisk_trim"]) if nd[i] >= 2 else (
                    (1.0 - 0.25 * p["derisk_trim"]) if nd[i] == 1 else 1.0)
                if dist[i]:
                    w *= (1.0 - p["derisk_trim"])
            out[i] = w
        elif upv[i]:
            in_pos, out[i] = True, 1.0
        elif dip[i]:
            in_pos, out[i] = True, p["dip_size"]
    return pd.Series(out, index=df.index, name="target")


class SignalEngine:
    """仓库回测框架入口: generate(data_map) -> {code: target_weights}。"""

    def generate(self, data_map: dict) -> dict:
        code = next(iter(data_map))
        try:
            df = build_features()
        except Exception:            # 本地 CSV 不可用时退化为框架传入的数据
            raw = data_map[code].copy()
            raw.index = pd.to_datetime(raw.index)
            df = raw.sort_index()
            for n in (20, 60):
                df[f"ma{n}"] = df["close"].rolling(n).mean()
            df["ma20_slope"] = (df["ma20"] - df["ma20"].shift(10)) / df["ma20"].shift(10).abs() / 10 * 100
            for col, dflt in (("dist_ma20", 0.0), ("ret3", 0.0), ("ret5", 0.0),
                              ("rsi14", 50.0), ("atr_pct", 0.0), ("dd_high20", 0.0),
                              ("up_low20", 0.0), ("vol_ratio", 1.0), ("new_high20", 0),
                              ("turnover", 0.0)):
                if col not in df.columns:
                    df[col] = dflt
        tgt = generate_target(df)
        return {code: tgt}
