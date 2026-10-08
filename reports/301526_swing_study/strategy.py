"""国际复材 波段策略 — 多子策略 + 组合状态机

子策略(对应信号研究的证据):
  A. 趋势回踩买入 (TrendPullback)  — 主升浪中缩量回踩均线; 提供基础多头暴露
  B. 恐慌抄底     (PanicDip)       — 急跌+大盘同步+高波动; 唯一有效的"底部"形态
  C. 突破追涨     (Breakout)       — 20日新高+放量+未过度乖离
  D. 顶部派发减仓 (Derisk)         — 过热/杠杆换手极端/大宗折价减持/破位; 研究显示最稳的 alpha

组合: target_pos = w_regime * w_heat, 另加追踪止损覆盖。
所有阈值集中在 Params, 便于样本外验证与敏感性测试。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

import swing_lib as sl


@dataclass
class Params:
    # A 趋势回踩(主升浪缩量回踩均线)
    pull_lo: float = -8.0        # dist_ma20 下沿(%)
    pull_hi: float = 10.0        # dist_ma20 上沿(%)
    pull_vol: float = 1.1        # 回踩需缩量(量比上限)
    pull_rsi_lo: float = 35.0
    pull_rsi_hi: float = 75.0
    # B1 系统性恐慌(大盘同步急跌)
    dd20_panic: float = -13.0
    ret5_panic: float = -6.0
    idx5_panic: float = -1.5
    atr_panic: float = 4.0
    # B2 个股崩跌(与大盘脱钩, 需更深回撤才接)
    dd20_crash: float = -35.0
    ret5_crash: float = -10.0
    rsi_crash: float = 45.0
    # B3 强势股急回踩(主升浪中 3 日急跌, 均线未破)
    ret3_snap: float = -10.0
    dist20_snap: float = -3.0    # 回踩时仍不低于 MA20 太多
    panic_size: float = 0.7
    # C 突破
    bo_vol: float = 1.3
    bo_ext: float = 15.0         # 突破时乖离不要太大
    bo_idx_dd: float = -8.0      # 指数不能处于深跌
    # D 减仓
    dist20_hot: float = 18.0
    uplow20_hot: float = 40.0
    rz_z_hot: float = 2.0
    turn_hot: float = 12.0
    block_pct_hot: float = 0.25  # 20日大宗折价减持金额 / 流通市值 (%)
    slope_break: float = -0.3    # ma20 斜率转负
    # 风控
    trail_stop: float = 0.18     # 自持仓最高点回撤
    hard_stop: float = 0.20      # 自成本回撤
    cooldown: int = 2            # 离场后冷静期(天)
    w_neutral: float = 0.6       # 非趋势非恐慌时的基础仓位


def _c(df: pd.DataFrame, name: str, default=0.0) -> pd.Series:
    """取列, 缺失时返回常量(default) — 让策略在缺少融资融券/大宗数据时优雅降级。"""
    if name in df.columns:
        return df[name]
    return pd.Series(default, index=df.index, dtype=float)


def _flag(df: pd.DataFrame, name: str, cond: pd.Series, missing_default: bool = False) -> pd.Series:
    """若列缺失, 返回 missing_default 的常量(用于标记类信号)。"""
    if name in df.columns:
        return cond
    return pd.Series(missing_default, index=df.index)


def regime_and_heat(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    """返回各子策略的布尔信号与 regime 标记。缺列时对应信号自动降级。"""
    out = pd.DataFrame(index=df.index)
    trend = (df["ma20"] > df["ma60"]) & (df["ma20_slope"] > 0)
    breakdown = (df["close"] < df["ma20"]) & (df["ma20_slope"] < p.slope_break)

    # A 趋势回踩: 上升结构 + 回踩均线 + 缩量
    out["A_pullback"] = (trend
                         & df["dist_ma20"].between(p.pull_lo, p.pull_hi)
                         & (df["vol_ratio"] < p.pull_vol)
                         & df["rsi14"].between(p.pull_rsi_lo, p.pull_rsi_hi))

    # B1 系统性恐慌: 个股急跌 + 大盘同步走弱(缺指数数据则跳过该条件) + 波动放大
    idx_weak = _flag(df, "idx_cyb_ret5", df["idx_cyb_ret5"] < p.idx5_panic, True)
    out["B1_panic"] = ((df["dd_high20"] < p.dd20_panic)
                       & (df["ret5"] < p.ret5_panic)
                       & idx_weak
                       & (df["atr_pct"] > p.atr_panic))

    # B2 个股崩跌: 深度回撤 + 连续大跌(与大盘脱钩, 要求更深安全边际)
    out["B2_crash"] = ((df["dd_high20"] < p.dd20_crash)
                       & (df["ret5"] < p.ret5_crash)
                       & (df["rsi14"] < p.rsi_crash))

    # B3 强势股急回踩: 主升结构未破, 3日急跌
    out["B3_snapback"] = (trend
                          & (df["ret3"] < p.ret3_snap)
                          & (df["dist_ma20"] > p.dist20_snap))

    # C 突破(缺指数数据则跳过指数条件)
    idx_ok = _flag(df, "idx_cyb_dd60", df["idx_cyb_dd60"] > p.bo_idx_dd, True)
    out["C_breakout"] = ((df["new_high20"] == 1)
                         & (df["vol_ratio"] > p.bo_vol)
                         & (df["dist_ma20"] < p.bo_ext)
                         & idx_ok)

    # D 减仓证据(缺数据 -> 不触发)
    out["D_overheat"] = (df["dist_ma20"] > p.dist20_hot) & (df["up_low20"] > p.uplow20_hot)
    out["D_leverage"] = (_flag(df, "rz_z20", _c(df, "rz_z20") > p.rz_z_hot)
                         & (df["turnover"] > p.turn_hot))
    out["D_distribute"] = _flag(df, "block_amt20_pct",
                                _c(df, "block_amt20_pct") > p.block_pct_hot)
    out["D_breakdown"] = breakdown

    out["trend"] = trend
    out["breakdown"] = breakdown
    out["entry"] = out[["A_pullback", "B1_panic", "B2_crash", "B3_snapback",
                        "C_breakout"]].fillna(False).any(axis=1)
    out["n_derisk"] = (out[["D_overheat", "D_leverage", "D_distribute"]]
                       .fillna(False).sum(axis=1))
    # 顶背离: 创20日新高但 RSI 未创新高
    out["D_divergence"] = (df["new_high20"] == 1) & (df["rsi14"] < df["rsi14_prev3"])
    return out


def build_target_position(df: pd.DataFrame, p: Params, sig: pd.DataFrame | None = None
                          ) -> tuple[pd.Series, pd.Series]:
    """状态机: 逐日决定目标仓位(0~1), 含追踪/硬止损与冷静期。

    规则:
      - 空仓: 由 A/B/C 触发建仓 (B 用 panic_size 小仓试探)
      - 持仓: target = base_w * derisk_factor
              derisk_factor = 1 - 0.35*(n_derisk==1) - 0.65*(n_derisk>=2),
              大宗折价派发证据(D_distribute) 再打 5 折
      - 覆盖: 破位(D_breakdown) / 追踪止损 / 硬止损 -> 清零并进入冷静期
      - 持仓中新的回踩或突破且无过热 -> base_w 恢复满仓(趋势延续加回)
    返回 (target_pos, state) — state 记录当日触发原因, 便于归因。
    """
    if sig is None:
        sig = regime_and_heat(df, p)
    dates = df.index
    close = df["close"].to_numpy(float)
    target = np.zeros(len(df))
    reason = np.array([""] * len(df), dtype=object)

    in_pos = False
    entry_px = 0.0
    peak_px = 0.0
    base_w = 0.0
    cooldown = 0

    for i in range(len(df)):
        row = sig.iloc[i]
        px = close[i]
        want, why = 0.0, ""

        if in_pos:
            peak_px = max(peak_px, px)
            if px <= peak_px * (1 - p.trail_stop):
                want, why = 0.0, f"trail_stop({px / peak_px - 1:.1%})"
            elif px <= entry_px * (1 - p.hard_stop):
                want, why = 0.0, f"hard_stop({px / entry_px - 1:.1%})"
            elif row["D_breakdown"]:
                want, why = 0.0, "breakdown"
            else:
                k = int(row["n_derisk"])
                factor = 1.0 - 0.35 * (k == 1) - 0.65 * (k >= 2)
                if row["D_distribute"]:
                    factor *= 0.5
                if row["A_pullback"] or row["C_breakout"]:
                    # 趋势延续的重新确认: 允许把基准仓位加回
                    base_w = min(1.0, base_w + 0.35)
                    why = "add"
                else:
                    why = f"hold(k={k}{'+dist' if row['D_distribute'] else ''})"
                want = base_w * factor
        else:
            if cooldown > 0:
                cooldown -= 1
                want, why = 0.0, "cooldown"
            elif row["D_breakdown"]:
                want, why = 0.0, "wait_breakdown"
            elif row["B2_crash"]:
                want, why = p.panic_size, "B2_crash"
            elif row["B1_panic"]:
                want, why = p.panic_size, "B1_panic"
            elif row["B3_snapback"]:
                want, why = 0.8, "B3_snapback"
            elif row["A_pullback"]:
                want, why = 1.0, "A_pullback"
            elif row["C_breakout"]:
                want, why = 1.0, "C_breakout"

        if (not in_pos) and want > 0:
            in_pos, entry_px, peak_px, base_w = True, px, px, want
        elif in_pos and want <= 0:
            in_pos, base_w, cooldown = False, 0.0, p.cooldown
        target[i] = want
        reason[i] = why

    # 信号在 t 日收盘生成, t+1 开盘成交
    return pd.Series(target, index=dates, name="target"), pd.Series(reason, index=dates, name="state")


def single_strategy(df: pd.DataFrame, name: str, p: Params | None = None) -> pd.Series:
    """单独跑某个子策略(用于对比贡献)。"""
    p = p or Params()
    sig = regime_and_heat(df, p)
    if name == "A":
        pos = sig["A_pullback"].astype(float)
    elif name == "B":
        pos = (sig["B1_panic"] | sig["B2_crash"]).astype(float) * p.panic_size
    elif name == "B3":
        pos = sig["B3_snapback"].astype(float) * 0.8
    elif name == "C":
        pos = sig["C_breakout"].astype(float)
    elif name == "D":
        # 纯顶部规避: 全程持有, 但过热/杠杆极端/派发/破位时清仓
        risky = (sig["D_overheat"] | sig["D_leverage"] | sig["D_distribute"]
                 | sig["D_breakdown"]).fillna(False)
        pos = (~risky).astype(float)
    elif name == "buyhold":
        pos = pd.Series(1.0, index=df.index)
    else:
        raise ValueError(name)
    return _apply_stops(df, pos, p)


def _apply_stops(df: pd.DataFrame, raw: pd.Series, p: Params) -> pd.Series:
    """给任意原始仓位序列套用追踪/硬止损与冷静期。"""
    close = df["close"].to_numpy(float)
    rawv = raw.to_numpy(float)
    out = np.zeros(len(df))
    in_pos, entry, peak, cd = False, 0.0, 0.0, 0
    for i in range(len(df)):
        px = close[i]
        if in_pos:
            peak = max(peak, px)
            if px <= peak * (1 - p.trail_stop) or px <= entry * (1 - p.hard_stop):
                in_pos, cd = False, p.cooldown
                out[i] = 0.0
                continue
            out[i] = rawv[i] if rawv[i] > 0 else 0.0
            if out[i] <= 0:
                in_pos, cd = False, p.cooldown
        else:
            if cd > 0:
                cd -= 1
                out[i] = 0.0
            elif rawv[i] > 0:
                in_pos, entry, peak = True, px, px
                out[i] = rawv[i]
    return pd.Series(out, index=df.index, name="target")


def evaluate_detection(df: pd.DataFrame, sig: pd.DataFrame, pct: float = 0.12,
                       tol_back: int = 2, tol_fwd: int = 3) -> dict:
    """波段顶/底检测的命中率(用 ZigZag 真值, 命中窗口 ±tol 天)。"""
    _, piv = sl.pivot_frame(df, pct)
    entry_sig = sig["entry"].fillna(False).to_numpy()
    derisk_cols = ["D_overheat", "D_leverage", "D_distribute", "D_breakdown", "D_divergence"]
    derisk_sig = pd.concat(
        [sig[c].fillna(False) if c in sig.columns else pd.Series(False, index=sig.index)
         for c in derisk_cols], axis=1).any(axis=1).to_numpy()
    res = {}
    for kind, sigv in (("bottom", entry_sig), ("top", derisk_sig)):
        tp = 0
        hits = []
        sub = piv[piv.kind == kind]
        for _, r in sub.iterrows():
            lo, hi = max(0, r["idx"] - tol_back), min(len(df) - 1, r["idx"] + tol_fwd)
            hit = bool(sigv[lo:hi + 1].any())
            tp += hit
            hits.append((r["date"].date(), hit))
        # 精确率: 信号日中有多少落在真值窗口附近
        piv_idx = set()
        for _, r in sub.iterrows():
            for j in range(max(0, r["idx"] - tol_back), min(len(df), r["idx"] + tol_fwd + 1)):
                piv_idx.add(j)
        n_sig_days = int(sigv.sum())
        win_days = sum(1 for j in range(len(df)) if sigv[j] and j in piv_idx)
        res[kind] = {
            "n_pivots": len(sub),
            "recall_pct": tp / len(sub) * 100 if len(sub) else np.nan,
            "n_signal_days": n_sig_days,
            "precision_pct": win_days / n_sig_days * 100 if n_sig_days else np.nan,
            "missed": [d for d, h in hits if not h],
        }
    return res


def run(df: pd.DataFrame, p: Params | None = None, *, start: str | None = None,
        end: str | None = None) -> dict:
    """完整回测: 组合策略 vs 买入持有。"""
    p = p or Params()
    sig = regime_and_heat(df, p)
    target, state = build_target_position(df, p, sig)
    sub = df if start is None and end is None else df.loc[start:end]
    tgt = target.loc[sub.index]
    res = {
        "params": asdict(p),
        "strategy": sl.backtest(sub, tgt),
        "buy_hold": sl.backtest(sub, pd.Series(1.0, index=sub.index)),
        "state": state.loc[sub.index],
        "signals": sig.loc[sub.index],
    }
    return res


def print_report(res: dict, label: str = "") -> None:
    s, b = res["strategy"].metrics, res["buy_hold"].metrics
    print(f"\n{'=' * 78}\n{label}\n{'=' * 78}")
    keys = [("total_return_pct", "总收益%"), ("cagr_pct", "年化%"),
            ("max_drawdown_pct", "最大回撤%"), ("sharpe", "Sharpe"),
            ("calmar", "Calmar"), ("vol_annual_pct", "年化波动%"),
            ("n_trades", "交易数"), ("win_rate_pct", "胜率%"),
            ("avg_win_pct", "平均盈利%"), ("avg_loss_pct", "平均亏损%"),
            ("profit_factor", "盈亏比"), ("avg_hold_days", "平均持仓天"),
            ("exposure_pct", "在场天数%")]
    print(f"{'指标':<12}{'策略':>12}{'买入持有':>12}{'差异':>12}")
    for k, name in keys:
        sv, bv = s.get(k, np.nan), b.get(k, np.nan)
        print(f"{name:<12}{sv:>12.2f}{bv:>12.2f}{sv - bv:>+12.2f}")
