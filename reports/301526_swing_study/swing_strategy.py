#!/usr/bin/env python3
"""A股波段趋势策略 —— 股票无关的可复用实现（301526 国际复材研究的固化版）

设计原则(来自 301526 研究的结论):
  1. 收益引擎只有一层: **趋势滞回带**(收盘 > MA20×(1+买带) 且 MA20>MA60 建仓;
     收盘 < MA20×(1-卖带) 或 MA20<MA60 离场; 中间地带维持原状态)。
     "卖带"抗震荡是关键 —— 容忍小跌破, 只在趋势真正坏掉时离场。
  2. 先手层(空仓时用小仓抢反弹)只保留 B1 系统性恐慌 + B2 个股崩跌;
     A 趋势回踩 / C 突破 / B3 强势急回踩 作为先手入场是**负贡献**(见 REPORT 11.5)。
  3. 顶部减仓层默认关闭 —— 统计上能识别顶(召回 93%), 但接进交易会亏掉主升
     (全样本 823% → 446%, 见 REPORT 4.3)。
  4. **必须先做适用性体检**: 本策略只在"长而干净的多段趋势"上有效。
     20 只同类标的测试: 捕获率中位仅 0.36, 只有 1 只跑赢买入持有(REPORT 12)。

用法:
    # 回测 + 适用性体检
    python swing_strategy.py --csv data/px_qfq.csv --preset balanced
    # 只做适用性判断(是否该用本策略)
    python swing_strategy.py --csv data/px_qfq.csv --check
    # 输出当前信号(供实盘/定时任务用)
    python swing_strategy.py --csv data/px_qfq.csv --signal
    # 跨标的批量体检
    python swing_strategy.py --batch data/peers/ --check
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# ─────────────── A股成本模型(创业板; 主板把涨跌停改成 0.099) ───────────────
COMMISSION = 0.00025      # 佣金 万2.5 双边
STAMP_TAX = 0.0005        # 印花税 0.05% 仅卖出
TRANSFER_FEE = 0.00001    # 过户费 0.001% 双边
SLIPPAGE = 0.001          # 滑点 0.1% 单边
LIMIT_PCT = 0.199         # 涨跌停不可成交判定阈值


# ═══════════════════════════ 参数 ═══════════════════════════

@dataclass
class Params:
    # ── 核心: 趋势滞回带 ──
    ma_fast: int = 20
    ma_slow: int = 60
    buy_band: float = 0.05    # 进场需高于 MA20 的幅度
    sell_band: float = 0.05   # 跌破 MA20 的容忍度(抗震荡的关键)
    # ── 先手层: B1 系统性恐慌 ──
    b1_dd20: float = -13.0    # 距20日高点回撤
    b1_ret5: float = -6.0     # 5日跌幅
    b1_idx5: float = -1.5     # 大盘(创业板指)5日跌幅
    b1_atr: float = 4.0       # ATR% 下限(波动放大确认)
    # ── 先手层: B2 个股崩跌 ──
    b2_dd20: float = -35.0
    b2_ret5: float = -10.0
    b2_rsi: float = 45.0
    dip_size: float = 0.7     # 先手仓位(未确认, 故不满仓)
    dip_set: str = "full"     # 先手子策略集: full=A|B1|B2|B3|C; b1b2=B1+B2; none=不抢反弹
    cross_filter: bool = True  # 是否要求 MA20>MA60(aggressive_trail 需关掉)
    # ── 可选叠加(默认关闭, 见 REPORT 11/13) ──
    margin_gate: bool = False      # 需 沪市两融余额20日变化>0 才允许先手
    derisk_trim: float = 0.0       # >0 时启用顶部减仓(过热/杠杆/派发), 会牺牲收益
    trail_stop: float = 0.0        # >0 时启用追踪止损(如 0.25 = 自高点回撤25%)
    # 顶部减仓阈值(仅 derisk_trim>0 时生效)
    dist20_hot: float = 18.0
    uplow20_hot: float = 40.0
    rz_z_hot: float = 2.0
    turn_hot: float = 12.0
    block_pct_hot: float = 0.25


# 经过验证的三档预设(REPORT 第 6/12 节)
PRESETS: dict[str, dict] = {
    # 均衡(推荐): 趋势滞回带 + B1/B2 先手; 301526 全样本 966.5%/-32.4%/Sharpe 1.97
    "balanced": {},                                    # 研究报告头条口径(966.47%)
    # 精简先手: 只留 B1+B2; 跨 9 只中位 137.9%→162.5% 但均值 298.9%→284.4%(复材 966%→862%, 变差)
    "slim_dip": {"dip_set": "b1b2"},
    # 保守: 只做趋势, 不抢反弹; 跨 20 只削回撤 18~19/20(中位 -45.9%→-30.1%)
    "trend_only": {"dip_set": "none"},
    # 加宏观过滤: 先手需"沪市两融余额20日变化>0"; 复材 931.5%(交易 33→21)
    "balanced_margin": {"margin_gate": True},
    # 激进: 满仓 + 25% 追踪止损(不做趋势过滤, 用 trend_only 关闭先手 + trail);
    #  跨 20 只捕获率中位 1.03、收益改善 13/20(但不削回撤)
    "aggressive_trail": {"buy_band": -1.0, "sell_band": 1.0, "dip_set": "none",
                         "cross_filter": False, "trail_stop": 0.25},
    # 削回撤优先: 买带0/卖带5(跨 9 只回撤改善 9/9, 收益只剩基准约 44%)
    "defensive": {"buy_band": 0.0, "sell_band": 0.05, "dip_set": "none"},
}
# 说明: aggressive_trail 用 buy_band=-1.0 (c>0 恒真) / sell_band=1.0 (c<0 恒假)
#       让趋势入场恒成立、趋势离场恒不触发,
#       等价于"始终满仓 + 追踪止损", 由 trail_stop 负责离场。


# ═══════════════════════════ 特征(严格因果) ═══════════════════════════

def _rsi(s: pd.Series, n: int) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50.0)


def build_features(df: pd.DataFrame, *, strict_lag: bool = True) -> pd.DataFrame:
    """因果特征。列名与研究报告口径一致。

    strict_lag=True: 交易所晚间披露类数据(融资融券/大宗)统一 shift(1), 偏保守。
    """
    d = df.copy()
    d.index = pd.to_datetime(d.index)
    d = d[~d.index.duplicated(keep="last")].sort_index()
    c, h, l, v = d["close"], d["high"], d["low"], d["volume"]

    for n in (3, 5, 10, 20, 60):
        d[f"ret{n}"] = c.pct_change(n) * 100
    for n in (5, 10, 20, 30, 60, 120):
        d[f"ma{n}"] = c.rolling(n).mean()
    d["dist_ma20"] = (c / d["ma20"] - 1) * 100
    d["ma20_slope"] = (d["ma20"] - d["ma20"].shift(10)) / d["ma20"].shift(10).abs() / 10 * 100
    d["rsi14"] = _rsi(c, 14)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    d["atr_pct"] = tr.ewm(alpha=1 / 14, adjust=False).mean() / c * 100
    d["dd_high20"] = (c / h.rolling(20).max() - 1) * 100
    d["up_low20"] = (c / l.rolling(20).min() - 1) * 100
    # 突破/新高用"前 N 日收盘高点"(不含当日), 与报告一致
    d["new_high20"] = (c > c.rolling(20).max().shift(1)).astype(int)
    d["vol_ratio"] = v / v.rolling(20).mean()
    if "turnover" in d.columns and d["turnover"].max() < 1.5:
        d["turnover"] = d["turnover"] * 100          # 新浪口径是小数

    # 杠杆 z 值(仅先手 gate / 顶部减仓用)
    if "rz_balance" in d.columns:
        rz = d["rz_balance"].shift(1) if strict_lag else d["rz_balance"]
        d["rz_z20"] = (rz - rz.rolling(120).mean()) / rz.rolling(120).std()
    return d.replace([np.inf, -np.inf], np.nan)


def attach_market(d: pd.DataFrame, market_close: pd.Series) -> pd.DataFrame:
    """挂上大盘(如创业板指)收盘价, 供 B1 的"大盘同步走弱"条件与 C 的指数过滤使用。"""
    d = d.copy()
    d["mkt_close"] = market_close.reindex(d.index).ffill()
    d["mkt_ret5"] = d["mkt_close"].pct_change(5) * 100
    d["mkt_dd60"] = (d["mkt_close"] / d["mkt_close"].rolling(60).max() - 1) * 100
    return d


def attach_margin_gate(d: pd.DataFrame, mkt_margin: pd.Series) -> pd.DataFrame:
    """挂上全市场两融余额(沪市单边即可), 供 margin_gate 使用。"""
    d = d.copy()
    m = mkt_margin.reindex(d.index).ffill()
    d["mkt_margin_chg20"] = m.pct_change(20) * 100
    return d


# ═══════════════════════════ 策略 ═══════════════════════════

def entry_signals(d: pd.DataFrame, p: Params) -> pd.DataFrame:
    """先手层子策略。B3/A/C 保留计算但不进入默认组合(负贡献, 见 REPORT 11.5)。"""
    s = pd.DataFrame(index=d.index)
    idx_weak = (d["mkt_ret5"] < p.b1_idx5) if "mkt_ret5" in d.columns else True
    idx_ok = (d["mkt_dd60"] > -8.0) if "mkt_dd60" in d.columns else True
    trend = (d["ma20"] > d["ma60"]) & (d["ma20_slope"] > 0)

    s["B1_panic"] = ((d["dd_high20"] < p.b1_dd20) & (d["ret5"] < p.b1_ret5)
                     & idx_weak & (d["atr_pct"] > p.b1_atr))
    s["B2_crash"] = ((d["dd_high20"] < p.b2_dd20) & (d["ret5"] < p.b2_ret5)
                     & (d["rsi14"] < p.b2_rsi))
    s["B3_snapback"] = trend & (d["ret3"] < -10.0) & (d["dist_ma20"] > -3.0)
    s["A_pullback"] = (trend & d["dist_ma20"].between(-8.0, 10.0)
                       & (d["vol_ratio"] < 1.1) & d["rsi14"].between(35.0, 75.0))
    s["C_breakout"] = ((d["new_high20"] == 1) & (d["vol_ratio"] > 1.3)
                       & (d["dist_ma20"] < 15.0) & idx_ok)
    s["D_overheat"] = (d["dist_ma20"] > p.dist20_hot) & (d["up_low20"] > p.uplow20_hot)
    s["D_leverage"] = (d.get("rz_z20", pd.Series(-9, index=d.index)) > p.rz_z_hot) \
        & (d.get("turnover", pd.Series(0.0, index=d.index)) > p.turn_hot)
    s["D_distribute"] = d.get("block_amt20_pct", pd.Series(-9, index=d.index)) > p.block_pct_hot
    s["D_breakdown"] = (d["close"] < d["ma20"]) & (d["ma20_slope"] < -0.3)
    s["n_derisk"] = s[["D_overheat", "D_leverage", "D_distribute"]].fillna(False).sum(axis=1)
    return s


def target_position(d: pd.DataFrame, p: Params | None = None,
                    preset: str = "balanced", *,
                    dip_mask: pd.Series | None = None,
                    dip_scale: pd.Series | None = None) -> tuple[pd.Series, pd.Series]:
    """状态机 → (目标仓位, 决策原因)。t 日收盘决策, t+1 开盘成交。

    dip_mask / dip_scale 用于研究: 覆盖先手层的触发条件与仓位缩放。
    ⚠️ 研究时若要"只保留部分子策略", 必须用 dip_mask **重跑状态机**,
       不能拿全集合的轨迹事后清零 —— 后者只能删不能加, 会连带丢掉受限集合
       本应在次日发生的新入场(2026-07-10 那次 B1 就被这样丢掉过)。
    """
    p = p or Params()
    if preset not in PRESETS:
        raise ValueError(f"未知预设 {preset}; 可选 {list(PRESETS)}")
    p = Params(**{**asdict(p), **PRESETS[preset]})
    s = entry_signals(d, p)
    c, ma20, ma60 = d["close"], d["ma20"], d["ma60"]
    if dip_mask is None:
        _map = {"A": "A_pullback", "B1": "B1_panic", "B2": "B2_crash",
                "B3": "B3_snapback", "C": "C_breakout"}
        _sets = {"full": ("A", "B1", "B2", "B3", "C"), "b1b2": ("B1", "B2"), "none": ()}
        allow_dip = pd.Series(False, index=d.index)
        for _k in _sets[p.dip_set]:
            allow_dip = allow_dip | s[_map[_k]].fillna(False)
        if p.margin_gate and "mkt_margin_chg20" in d.columns:
            allow_dip = allow_dip & (d["mkt_margin_chg20"] > 0).fillna(False)
    else:
        allow_dip = dip_mask.reindex(d.index).fillna(False).astype(bool)
    scale = (dip_scale.reindex(d.index).fillna(1.0) if dip_scale is not None
             else pd.Series(1.0, index=d.index))

    if p.cross_filter:
        up = (c > ma20 * (1 + p.buy_band)) & (ma20 > ma60)
        dn = (c < ma20 * (1 - p.sell_band)) | (ma20 < ma60)
    else:
        # 不做趋势交叉过滤(aggressive_trail): 只靠 buy/sell 带与追踪止损控制
        up = c > ma20 * (1 + p.buy_band)
        dn = c < ma20 * (1 - p.sell_band)
    cn, upv, dnv = c.to_numpy(float), up.to_numpy(bool), dn.to_numpy(bool)
    dip, nd = allow_dip.to_numpy(bool), s["n_derisk"].fillna(0).to_numpy()
    dist = s["D_distribute"].fillna(False).to_numpy()
    sc = scale.to_numpy(float)

    out = np.zeros(len(d))
    why = np.array([""] * len(d), dtype=object)
    in_pos, peak = False, 0.0
    for i in range(len(d)):
        if in_pos:
            peak = max(peak, cn[i])
            if p.trail_stop and cn[i] <= peak * (1 - p.trail_stop):
                in_pos = False
                why[i] = f"追踪止损({cn[i] / peak - 1:.1%})"
                continue
            if dnv[i]:
                in_pos = False
                why[i] = "跌破MA20×卖带" if cn[i] < ma20.iloc[i] else "MA20下穿MA60"
                continue
            w = 1.0
            if p.derisk_trim > 0:
                w *= (1 - 0.5 * p.derisk_trim) if nd[i] >= 2 else (
                    (1 - 0.25 * p.derisk_trim) if nd[i] == 1 else 1.0)
                if dist[i]:
                    w *= (1 - p.derisk_trim)
            out[i], why[i] = w, "持有"
        elif upv[i]:
            in_pos, peak, out[i], why[i] = True, cn[i], 1.0, "趋势确认建仓"
        elif dip[i] and p.dip_size > 0:
            in_pos, peak = True, cn[i]
            out[i] = p.dip_size * sc[i]
            why[i] = "先手:" + ("B1恐慌" if s["B1_panic"].iloc[i] else "B2崩跌")
    return pd.Series(out, index=d.index, name="target"), pd.Series(why, index=d.index, name="reason")


def dip_mask_of(d: pd.DataFrame, names: tuple, p: Params | None = None) -> pd.Series:
    """按子策略名构造先手触发掩码(研究用)。names ⊂ {A,B1,B2,B3,C}。"""
    s = entry_signals(d, p or Params())
    m = {"A": "A_pullback", "B1": "B1_panic", "B2": "B2_crash",
         "B3": "B3_snapback", "C": "C_breakout"}
    out = pd.Series(False, index=d.index)
    for k in names:
        out = out | s[m[k]].fillna(False)
    return out


# ═══════════════════════════ 回测 ═══════════════════════════

def backtest(d: pd.DataFrame, target: pd.Series, *, initial: float = 1_000_000.0,
             cost: bool = True) -> dict:
    """日频回测: 信号 t 日收盘生成 → t+1 开盘成交; 含涨跌停不可成交约束。"""
    op = d["open"].to_numpy(float)
    cl = d["close"].to_numpy(float)
    prev = (d["close"].to_numpy(float)[:-1] if "close" in d else cl)
    prev = np.r_[np.nan, cl[:-1]]
    tgt = target.reindex(d.index).fillna(0.0).clip(0, 1).to_numpy(float)
    slip = SLIPPAGE if cost else 0.0
    comm = COMMISSION if cost else 0.0
    stamp = STAMP_TAX if cost else 0.0
    tf = TRANSFER_FEE if cost else 0.0

    cash, shares = initial, 0.0
    eq_curve, trades = [], []
    cur = None
    for i in range(len(d)):
        if i > 0:
            want = tgt[i - 1]
            eq = cash + shares * op[i]
            delta = ((eq * want) / op[i] if op[i] > 0 else 0.0) - shares
            chg = op[i] / prev[i] - 1 if np.isfinite(prev[i]) and prev[i] > 0 else 0.0
            if abs(delta) * op[i] > max(0.005 * eq, 1e-9):
                if delta > 0 and chg <= LIMIT_PCT:
                    px = op[i] * (1 + slip)
                    n = np.floor(min(delta, cash / (px * (1 + comm + tf))))
                    if n > 0:
                        cash -= n * px * (1 + comm + tf)
                        shares += n
                        if cur is None:
                            cur = {"e_dt": d.index[i], "e_px": px, "n": n}
                        else:
                            tot = cur["n"] + n
                            cur["e_px"] = (cur["e_px"] * cur["n"] + px * n) / tot
                            cur["n"] = tot
                elif delta < 0 and chg >= -LIMIT_PCT:
                    px = op[i] * (1 - slip)
                    n = min(-delta, shares)
                    if n > 0:
                        cash += n * px * (1 - comm - stamp - tf)
                        shares -= n
                        if cur is not None and shares <= 1e-9:
                            trades.append({"entry": cur["e_dt"], "exit": d.index[i],
                                           "entry_px": cur["e_px"], "exit_px": px,
                                           "ret": px / cur["e_px"] - 1,
                                           "hold_days": (d.index[i] - cur["e_dt"]).days})
                            cur = None
        eq_curve.append(cash + shares * cl[i])
    eq = pd.Series(eq_curve, index=d.index)
    if cur is not None:
        trades.append({"entry": cur["e_dt"], "exit": d.index[-1], "entry_px": cur["e_px"],
                       "exit_px": cl[-1], "ret": cl[-1] / cur["e_px"] - 1,
                       "hold_days": (d.index[-1] - cur["e_dt"]).days})
    ret = eq.pct_change().fillna(0)
    yrs = len(eq) / 252
    dd = eq / eq.cummax() - 1
    vol = ret.std() * np.sqrt(252)
    wins = [t for t in trades if t["ret"] > 0]
    gp = sum(t["ret"] for t in wins)
    gl = -sum(t["ret"] for t in trades if t["ret"] <= 0)
    return {
        "equity": eq, "trades": trades,
        "metrics": {
            "total_return_pct": (eq.iloc[-1] / eq.iloc[0] - 1) * 100,
            "cagr_pct": ((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100 if yrs > 0 else np.nan,
            "max_drawdown_pct": dd.min() * 100,
            "sharpe": (ret.mean() * 252 - 0.02) / vol if vol > 0 else np.nan,
            "calmar": (((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) / abs(dd.min()))
            if yrs > 0 and dd.min() < 0 else np.nan,
            "vol_annual_pct": vol * 100,
            "n_trades": len(trades),
            "win_rate_pct": len(wins) / len(trades) * 100 if trades else np.nan,
            "profit_factor": gp / gl if gl > 0 else np.nan,
            "avg_hold_days": np.mean([t["hold_days"] for t in trades]) if trades else np.nan,
        },
    }


# ═══════════════════════════ 适用性体检 ═══════════════════════════

def suitability(d: pd.DataFrame, p: Params | None = None, preset: str = "balanced") -> dict:
    """把规则套到目标标的上, 判断它是否适合本策略。

    捕获率 = 策略收益 / 买入持有收益。20 只同类标的实测:
      >0.7 适配 / 0.4~0.7 只当风控层 / <0.4 别用趋势过滤(见 REPORT 12.4)
    """
    d = build_features(d)
    pos, _ = target_position(d, p, preset)
    strat = backtest(d, pos)["metrics"]
    bh = backtest(d, pd.Series(1.0, index=d.index))["metrics"]
    cap = strat["total_return_pct"] / bh["total_return_pct"] if bh["total_return_pct"] > 0 else np.nan
    verdict = ("适配: 可用完整配置(含先手层)" if cap > 0.7 else
               "仅作风控层: 收益让渡换回撤控制" if cap >= 0.4 else
               "不适用: 改用 满仓+2.0~2.5×ATR追踪, 或长期持有")
    return {"捕获率": cap, "策略收益%": strat["total_return_pct"],
            "持有收益%": bh["total_return_pct"], "策略回撤%": strat["max_drawdown_pct"],
            "持有回撤%": bh["max_drawdown_pct"], "Sharpe": strat["sharpe"],
            "交易数": strat["n_trades"], "结论": verdict}


# ═══════════════════════════ CLI ═══════════════════════════

def load_csv(path: str) -> pd.DataFrame:
    d = pd.read_csv(path)
    dc = next((c for c in ("date", "日期", "trade_date") if c in d.columns), d.columns[0])
    d[dc] = pd.to_datetime(d[dc])
    return d.set_index(dc).sort_index()


def _market_series(path: str | None) -> pd.Series | None:
    """读大盘指数序列(取 close 列)。"""
    if not path or not Path(path).exists():
        return None
    m = load_csv(path)
    return m["close"] if "close" in m.columns else None


def _margin_series(path: str | None) -> pd.Series | None:
    """读全市场两融余额。优先用沪市单边(完整), 其次两市合计。

    ⚠️ akshare 的深市两融数据在 2024-06~2025-06 系统性缺失 177 个交易日,
       用"两市合计 + ffill"会伪造出"杠杆无变化"的假信号, 故优先沪市单边。
    """
    if not path or not Path(path).exists():
        return None
    m = load_csv(path)
    for c in ("mkt_rz_balance_sh", "mkt_rz_balance", "mkt_rz_balance_total"):
        if c in m.columns:
            return m[c]
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="A股波段趋势策略(股票无关)")
    ap.add_argument("--csv", help="OHLCV CSV(需含 date/open/high/low/close/volume)")
    ap.add_argument("--batch", help="批量体检: 目录下的 *.csv")
    ap.add_argument("--market", default=None, help="大盘指数 CSV(如 data/idx_cyb.csv), 供 B1 用")
    ap.add_argument("--margin", default=None, help="全市场两融 CSV(沪市单边), 供 margin_gate 用")
    ap.add_argument("--preset", default="balanced", choices=list(PRESETS))
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--check", action="store_true", help="只做适用性体检")
    ap.add_argument("--signal", action="store_true", help="输出最新信号(JSON)")
    args = ap.parse_args()

    if args.batch:
        rows = []
        for f in sorted(Path(args.batch).glob("*.csv")):
            try:
                d = load_csv(str(f))
                mkt = _market_series(args.market)
                if mkt is not None:
                    d = attach_market(d, mkt)
                r = suitability(d, preset=args.preset)
                r["标的"] = f.stem
                rows.append(r)
            except Exception as exc:  # noqa: BLE001
                print(f"  {f.stem}: {type(exc).__name__}: {exc}")
        t = pd.DataFrame(rows)
        cols = ["标的", "捕获率", "策略收益%", "持有收益%", "策略回撤%", "持有回撤%", "Sharpe", "交易数", "结论"]
        print(t[cols].round(2).to_string(index=False))
        print(f"\n捕获率中位 {t['捕获率'].median():.2f} | 回撤改善 "
              f"{(t['策略回撤%'] > t['持有回撤%']).sum()}/{len(t)} | "
              f"收益改善 {(t['策略收益%'] > t['持有收益%']).sum()}/{len(t)}")
        return

    if not args.csv:
        ap.error("需要 --csv 或 --batch")

    d = load_csv(args.csv)
    mkt = _market_series(args.market)
    if mkt is not None:
        d = attach_market(d, mkt)
    mg = _margin_series(args.margin)
    if mg is not None:
        d = attach_margin_gate(d, mg)

    if args.signal:
        feat = build_features(d)
        pos, why = target_position(feat, preset=args.preset)
        out = {"as_of": str(feat.index[-1].date()), "close": float(feat["close"].iloc[-1]),
               "preset": args.preset, "target_position": float(pos.iloc[-1]),
               "reason": str(why.iloc[-1]),
               "above_ma20": bool(feat["close"].iloc[-1] > feat["ma20"].iloc[-1]),
               "ma20_gt_ma60": bool(feat["ma20"].iloc[-1] > feat["ma60"].iloc[-1]),
               "dist_ma20_pct": float(feat["dist_ma20"].iloc[-1])}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    if args.check:
        r = suitability(d, preset=args.preset)
        for k, v in r.items():
            print(f"  {k:12s} {v if isinstance(v, str) else round(float(v), 2)}")
        return

    feat = build_features(d)
    sub = feat if not (args.start or args.end) else feat.loc[args.start:args.end]
    pos, why = target_position(feat, preset=args.preset)
    res = backtest(sub, pos.loc[sub.index])
    bh = backtest(sub, pd.Series(1.0, index=sub.index))
    print(f"\n=== {Path(args.csv).stem} | 预设 {args.preset} | "
          f"{sub.index.min().date()}~{sub.index.max().date()} ({len(sub)} bars) ===")
    print(f"{'指标':<14}{'策略':>12}{'买入持有':>12}")
    for k, nm in (("total_return_pct", "总收益%"), ("cagr_pct", "年化%"),
                  ("max_drawdown_pct", "最大回撤%"), ("sharpe", "Sharpe"),
                  ("calmar", "Calmar"), ("n_trades", "交易数"),
                  ("win_rate_pct", "胜率%"), ("profit_factor", "盈亏比"),
                  ("avg_hold_days", "平均持仓天")):
        print(f"{nm:<14}{res['metrics'][k]:>12.2f}{bh['metrics'][k]:>12.2f}")
    tr = pd.DataFrame(res["trades"])
    if len(tr):
        print(f"\n交易明细({len(tr)} 笔):")
        tr["entry"] = tr["entry"].dt.date
        tr["exit"] = tr["exit"].dt.date
        print(tr.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
