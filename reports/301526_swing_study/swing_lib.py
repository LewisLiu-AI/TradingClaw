"""国际复材(301526.SZ) 波段策略研究 — 核心库

模块内容:
  1. load_panel()      : 汇聚所有数据源为单一 DataFrame(日频)
  2. add_features()    : 因果特征工程(严格只用 t 及之前的信息)
  3. zigzag_pivots()   : ZigZag 波段真值标注(仅用于评估, 不进入策略)
  4. Backtester        : A股日频回测(T+1 / 涨跌停 / 佣金 / 印花税 / 过户费 / 滑点)
  5. metrics()         : 收益风险指标

时序约定(关键, 防前视):
  - t 日收盘后可得: 行情(OHLCV/换手)、东财资金流(盘中衍生, 收盘定稿)
  - t 日晚间披露: 融资融券明细、龙虎榜  -> 统一 shift(1) 使用, 偏保守
  - 季度数据(股东户数): 报告期后滞后 45 天
  - 所有信号在 t 日收盘生成, t+1 开盘成交
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"

# ── A股交易成本(创业板) ──
COMMISSION = 0.00025      # 佣金 万2.5, 双边
STAMP_TAX = 0.0005        # 印花税 0.05%, 仅卖出
TRANSFER_FEE = 0.00001    # 过户费 0.001%, 双边
SLIPPAGE = 0.001          # 滑点 0.1%(单边)
LIMIT_PCT = 0.199         # 创业板 20% 涨跌停, 留 0.1% 容差


# ════════════════════════════ 数据汇聚 ════════════════════════════


def _read(name: str, date_col: str = "date") -> pd.DataFrame | None:
    p = DATA / f"{name}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    if date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.set_index(date_col).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def load_panel() -> pd.DataFrame:
    """前复权行情为主表, 左连接各辅助数据源。"""
    px = _read("px_qfq").copy()
    px = px.rename(columns={"close": "close", "volume": "volume"})
    # 新浪口径换手率是小数(0.0433), 统一为百分数
    if px["turnover"].max() < 1.5:
        px["turnover"] = px["turnover"] * 100

    raw = _read("px_raw")
    px["close_raw"] = raw["close"]
    px["prev_close_raw"] = raw["close"].shift(1)

    # 复权因子(前复权/不复权), 用于检查除权跳空
    px["adj_factor"] = px["close"] / px["close_raw"]

    for name, cols in (
        ("idx_cyb", ["close"]),
        ("idx_hs300", ["close"]),
    ):
        d = _read(name)
        if d is not None:
            tag = "cyb" if "cyb" in name else "hs300"
            px[f"idx_{tag}"] = d["close"]

    m = _read("margin")
    if m is not None:
        for c in ("rz_balance", "rz_buy", "rz_net", "rz_balance_pct_float",
                  "rq_balance", "float_mktcap", "rzrq_balance"):
            if c in m.columns:
                px[c] = m[c]

    mf = _read("moneyflow")
    if mf is not None:
        for c in ("main_net", "main_pct", "super_net", "big_net", "small_net"):
            if c in mf.columns:
                px[c] = mf[c]

    bt = _read("block_trade")
    if bt is not None:
        px["block_amount"] = bt["amount"].resample("D").sum().reindex(px.index).fillna(0.0)
        prem = bt.assign(w=bt["amount"]).groupby(level=0).apply(
            lambda g: np.average(g["premium_pct"], weights=g["w"]) if g["w"].sum() else np.nan
        )
        px["block_premium"] = prem.reindex(px.index)

    lhb = _read("lhb")
    if lhb is not None:
        px["lhb_net"] = lhb["lhb_net"].resample("D").sum().reindex(px.index).fillna(0.0)

    hd = _read("holders")
    if hd is not None and "holders" in hd.columns:
        s = hd["holders"].astype(float)
        s.index = s.index + pd.Timedelta(days=45)  # 披露滞后
        px["holders"] = s.reindex(px.index.union(s.index)).ffill().reindex(px.index)

    inst = _read("inst_participation")
    if inst is not None:
        col = [c for c in inst.columns if "participation" in c]
        if col:
            px["inst_participation"] = inst[col[0]].reindex(px.index)

    px = px.loc[:, ~px.columns.duplicated()]
    return px


# ════════════════════════════ 特征工程 ════════════════════════════


def _rsi(s: pd.Series, n: int) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _slope(s: pd.Series, n: int) -> pd.Series:
    """归一化斜率: 每 bar 变化 / 均值。"""
    return (s - s.shift(n)) / s.shift(n).abs() / n


def add_features(px: pd.DataFrame, strict_lag: bool = True) -> pd.DataFrame:
    """因果特征。strict_lag=True 时, 交易所晚间披露类数据统一滞后 1 日。"""
    df = px.copy()
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    df["ret1"] = c.pct_change() * 100
    for n in (3, 5, 10, 20, 60):
        df[f"ret{n}"] = c.pct_change(n) * 100

    for n in (5, 10, 20, 30, 60, 120):
        df[f"ma{n}"] = c.rolling(n).mean()
        df[f"dist_ma{n}"] = (c / df[f"ma{n}"] - 1) * 100
    df["ma20_slope"] = _slope(df["ma20"], 10) * 100
    df["ma60_slope"] = _slope(df["ma60"], 20) * 100
    df["ma_align"] = ((df["ma5"] > df["ma10"]) & (df["ma10"] > df["ma20"])
                      & (df["ma20"] > df["ma60"])).astype(int)

    df["rsi2"] = _rsi(c, 2)
    df["rsi14"] = _rsi(c, 14)
    df["rsi14_prev3"] = df["rsi14"].shift(3)

    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    df["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["atr_pct"] = df["atr14"] / c * 100
    df["amp"] = (h - l) / c.shift() * 100

    ma20v = c.rolling(20).mean()
    sd20 = c.rolling(20).std()
    df["bb_z"] = (c - ma20v) / (2 * sd20)
    df["bb_width"] = (4 * sd20) / ma20v * 100

    for n in (20, 60, 120, 250):
        df[f"dd_high{n}"] = (c / h.rolling(n).max() - 1) * 100   # 距N日高点(负值)
        df[f"up_low{n}"] = (c / l.rolling(n).min() - 1) * 100    # 距N日低点
    df["new_high20"] = (c > c.rolling(20).max().shift(1)).astype(int)
    df["new_high60"] = (c > c.rolling(60).max().shift(1)).astype(int)
    df["new_low20"] = (c < c.rolling(20).min().shift(1)).astype(int)

    vma20 = v.rolling(20).mean()
    df["vol_ratio"] = v / vma20
    df["vol_ratio5"] = v.rolling(5).mean() / vma20
    df["vol_z"] = (v - vma20) / v.rolling(20).std()
    df["turnover_ma5"] = df["turnover"].rolling(5).mean()
    df["turn_dist"] = df["turnover"] / df["turnover"].rolling(120).mean()

    # K线形态
    body = (c - df["open"]) / df["open"] * 100
    df["body_pct"] = body
    rng = (h - l).replace(0, np.nan)
    df["upper_shadow"] = (h - np.maximum(c, df["open"])) / rng
    df["lower_shadow"] = (np.minimum(c, df["open"]) - l) / rng
    df["close_pos"] = (c - l) / rng            # 收盘在K线中的位置
    df["gap"] = (df["open"] / c.shift() - 1) * 100
    df["down_streak"] = (df["ret1"] < 0).astype(int).groupby(
        (df["ret1"] >= 0).cumsum()).cumsum()
    df["up_streak"] = (df["ret1"] > 0).astype(int).groupby(
        (df["ret1"] <= 0).cumsum()).cumsum()

    # 相对强度 / 市场
    for tag in ("cyb", "hs300"):
        col = f"idx_{tag}"
        if col in df.columns:
            df[f"idx_{tag}_ret5"] = df[col].pct_change(5) * 100
            df[f"idx_{tag}_ret20"] = df[col].pct_change(20) * 100
            df[f"idx_{tag}_dd60"] = (df[col] / df[col].rolling(60).max() - 1) * 100
            df[f"rs_{tag}_20"] = df["ret20"] - df[f"idx_{tag}_ret20"]
            # 滚动 beta(60日)
            r_s = df["ret1"]
            r_i = df[col].pct_change()
            cov = r_s.rolling(60).cov(r_i)
            var = r_i.rolling(60).var()
            df[f"beta60_{tag}"] = cov / var
            # 相对强度比价线
            df[f"rs_line_{tag}"] = (c / c.shift(20)) / (df[col] / df[col].shift(20))

    def lag(s: pd.Series) -> pd.Series:
        return s.shift(1) if strict_lag else s

    # 融资融券(交易所晚间披露)
    if "rz_balance" in df.columns:
        rz = lag(df["rz_balance"])
        df["rz_chg5"] = rz.pct_change(5) * 100
        df["rz_chg20"] = rz.pct_change(20) * 100
        df["rz_z20"] = (rz - rz.rolling(120).mean()) / rz.rolling(120).std()
        df["rz_net5"] = lag(df["rz_net"]).rolling(5).sum()
        if "float_mktcap" in df.columns:
            df["rz_net5_intensity"] = df["rz_net5"] / lag(df["float_mktcap"]) * 100
            df["rz_level"] = rz / lag(df["float_mktcap"]) * 100
        if "rq_balance" in df.columns:
            df["rq_chg20"] = lag(df["rq_balance"]).pct_change(20) * 100

    # 主力资金(东财, 收盘定稿 -> 不滞后)
    if "main_net" in df.columns:
        df["main_net5"] = df["main_net"].rolling(5).sum()
        df["main_net10"] = df["main_net"].rolling(10).sum()
        df["main_pct5"] = df["main_pct"].rolling(5).mean()

    # 大宗减持压力
    if "block_amount" in df.columns:
        ba = lag(df["block_amount"]).fillna(0.0)
        df["block_amt20"] = ba.rolling(20).sum()
        if "float_mktcap" in df.columns:
            df["block_amt20_pct"] = df["block_amt20"] / lag(df["float_mktcap"]) * 100
        df["block_flag20"] = (df["block_amt20"] > 0).astype(int)
        df["block_premium20"] = lag(df["block_premium"]).rolling(20).mean()

    if "lhb_net" in df.columns:
        df["lhb_net20"] = lag(df["lhb_net"]).rolling(20).sum()

    if "holders" in df.columns:
        df["holders_chg"] = df["holders"].pct_change() * 100

    if "inst_participation" in df.columns:
        ip = df["inst_participation"]
        df["inst_part_chg20"] = (ip / ip.shift(20) - 1) * 100

    return df


# ════════════════════════════ ZigZag 真值 ════════════════════════════


@dataclass
class Pivot:
    idx: int
    date: pd.Timestamp
    price: float
    kind: str          # 'bottom' | 'top'
    confirm_idx: int = -1   # 该转折被"事后确认"的位置(仅用于评估滞后)


def zigzag_pivots(price: pd.Series, pct: float = 0.12) -> list[Pivot]:
    """经典 ZigZag: 自上一个确认极值反向走 >= pct 时, 确认前一个极值为转折点。

    仅用于事后评估("真值"), 不作为交易信号。confirm_idx 记录确认时点,
    用于衡量"最早可能识别日"。
    """
    p = price.to_numpy(dtype=float)
    dates = price.index
    piv: list[Pivot] = []
    if len(p) < 2:
        return piv

    direction = 0                      # 1=自底部上行(在找顶), -1=自顶部下行(在找底)
    ext_i, ext_p = 0, p[0]             # 当前方向的运行极值
    alt_i, alt_p = 0, p[0]             # 反向极值(未定方向时使用)

    for i in range(1, len(p)):
        if direction == 1:
            if p[i] > ext_p:
                ext_i, ext_p = i, p[i]
            elif p[i] <= ext_p * (1 - pct):
                piv.append(Pivot(ext_i, dates[ext_i], ext_p, "top", i))
                direction, ext_i, ext_p = -1, i, p[i]
        elif direction == -1:
            if p[i] < ext_p:
                ext_i, ext_p = i, p[i]
            elif p[i] >= ext_p * (1 + pct):
                piv.append(Pivot(ext_i, dates[ext_i], ext_p, "bottom", i))
                direction, ext_i, ext_p = 1, i, p[i]
        else:
            # 未定方向: 同时跟踪两个极值, 由先触发的反向幅度确定首个转折
            if p[i] > ext_p:
                ext_i, ext_p = i, p[i]
            if p[i] < alt_p:
                alt_i, alt_p = i, p[i]
            if p[i] >= alt_p * (1 + pct):
                piv.append(Pivot(alt_i, dates[alt_i], alt_p, "bottom", i))
                direction, ext_i, ext_p = 1, i, p[i]
            elif p[i] <= ext_p * (1 - pct):
                piv.append(Pivot(ext_i, dates[ext_i], ext_p, "top", i))
                direction, ext_i, ext_p = -1, i, p[i]
    return piv


def pivot_frame(px: pd.DataFrame, pct: float = 0.12) -> tuple[pd.DataFrame, pd.DataFrame]:
    """在日线上标注 pivot_type: 1=底, -1=顶, 0=无。"""
    piv = zigzag_pivots(px["close"], pct)
    out = pd.DataFrame({"pivot_type": 0}, index=px.index)
    rows = []
    for p in piv:
        out.iloc[p.idx, out.columns.get_loc("pivot_type")] = 1 if p.kind == "bottom" else -1
        rows.append({"idx": p.idx, "date": p.date, "price": p.price, "kind": p.kind,
                     "confirm_idx": p.confirm_idx,
                     "confirm_date": px.index[p.confirm_idx] if 0 <= p.confirm_idx < len(px) else pd.NaT})
    return out, pd.DataFrame(rows)


def swing_stats(piv: pd.DataFrame) -> pd.DataFrame:
    """相邻 pivot 之间的波段幅度/时长统计。"""
    if len(piv) < 2:
        return pd.DataFrame()
    d = piv.copy()
    d["next_price"] = d["price"].shift(-1)
    d["next_date"] = d["date"].shift(-1)
    d["ret"] = (d["next_price"] / d["price"] - 1) * 100
    d["days"] = (d["next_date"] - d["date"]).dt.days
    return d.dropna(subset=["next_price"])


# ════════════════════════════ 回测引擎 ════════════════════════════


@dataclass
class Trade:
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_px: float
    exit_px: float
    pos: float
    ret: float
    pnl: float
    hold_days: int
    reason: str = ""
    tags: tuple = field(default_factory=tuple)


@dataclass
class BacktestResult:
    equity: pd.Series
    positions: pd.Series
    trades: list[Trade]
    metrics: dict
    daily: pd.DataFrame = field(default_factory=pd.DataFrame)


def backtest(px: pd.DataFrame, target_pos: pd.Series, *,
             initial: float = 1_000_000.0, tag_map: pd.Series | None = None,
             cost: bool = True) -> BacktestResult:
    """日频回测。target_pos[t] 为 t 日收盘决策的目标仓位(0~1), t+1 开盘成交。

    约束: 涨跌停不可成交; 卖出资金 T+1 可用(简化: 单标的不影响)。
    """
    dates = px.index
    op, cl = px["open"].to_numpy(float), px["close"].to_numpy(float)
    raw_c = px["close_raw"].to_numpy(float) if "close_raw" in px.columns else cl
    raw_prev = px["prev_close_raw"].to_numpy(float) if "prev_close_raw" in px.columns else np.r_[np.nan, raw_c[:-1]]
    tgt = target_pos.reindex(dates).fillna(0.0).clip(0, 1).to_numpy(float)

    cash, shares = initial, 0.0
    equity_curve, pos_curve = [], []
    trades: list[Trade] = []
    cur: dict | None = None
    slip = SLIPPAGE if cost else 0.0
    comm = COMMISSION if cost else 0.0
    stamp = STAMP_TAX if cost else 0.0
    tf = TRANSFER_FEE if cost else 0.0

    def limit_hit(i: int, side: str) -> bool:
        """i 日是否因涨跌停无法按 open 成交。"""
        if i == 0 or not np.isfinite(raw_prev[i]) or not np.isfinite(op[i]):
            return False
        chg = op[i] / raw_prev[i] - 1
        return (side == "buy" and chg > LIMIT_PCT) or (side == "sell" and chg < -LIMIT_PCT)

    for i in range(len(dates)):
        # ---- 开盘: 执行上一日收盘的决策 ----
        if i > 0:
            want = tgt[i - 1]
            eq = cash + shares * op[i]
            target_shares = (eq * want) / op[i] if op[i] > 0 else 0.0
            delta = target_shares - shares
            if abs(delta) * op[i] > max(0.005 * eq, 1e-9):   # 忽略极小调仓
                if delta > 0 and not limit_hit(i, "buy"):
                    px_exec = op[i] * (1 + slip)
                    unit_cost = px_exec * (1 + comm + tf)     # 含成本的每股占款
                    n = min(delta, cash / unit_cost) if unit_cost > 0 else 0.0
                    n = np.floor(n)                           # 整股
                    if n > 0:
                        cash -= n * unit_cost
                        shares += n
                        if cur is None:
                            cur = {"entry_date": dates[i], "entry_px": px_exec,
                                   "shares": n, "tags": (tag_map.iloc[i - 1],)
                                   if tag_map is not None else ()}
                        else:
                            # 加仓: 加权成本
                            tot = cur["shares"] + n
                            cur["entry_px"] = (cur["entry_px"] * cur["shares"] + px_exec * n) / tot
                            cur["shares"] = tot
                elif delta < 0 and not limit_hit(i, "sell"):
                    px_exec = op[i] * (1 - slip)
                    n = min(-delta, shares)
                    if n > 0:
                        cash += n * px_exec * (1 - comm - stamp - tf)
                        shares -= n
                        if cur is not None and shares <= 1e-9:
                            tr = Trade(cur["entry_date"], dates[i], cur["entry_px"], px_exec,
                                       cur["shares"],
                                       px_exec / cur["entry_px"] - 1,
                                       (px_exec / cur["entry_px"] - 1) * cur["shares"] * cur["entry_px"],
                                       (dates[i] - cur["entry_date"]).days,
                                       "flat", cur["tags"])
                            trades.append(tr)
                            cur = None
        eq_close = cash + shares * cl[i]
        equity_curve.append(eq_close)
        pos_curve.append(shares * cl[i] / eq_close if eq_close > 0 else 0.0)

    eq = pd.Series(equity_curve, index=dates, name="equity")
    pos = pd.Series(pos_curve, index=dates, name="position")
    if cur is not None:                     # 末日仍持仓 -> 计入浮盈交易
        last_px = cl[-1]
        trades.append(Trade(cur["entry_date"], dates[-1], cur["entry_px"], last_px,
                            cur["shares"], last_px / cur["entry_px"] - 1,
                            (last_px / cur["entry_px"] - 1) * cur["shares"] * cur["entry_px"],
                            (dates[-1] - cur["entry_date"]).days, "open_at_end", cur["tags"]))
    m = metrics(eq, pos, trades)
    return BacktestResult(eq, pos, trades, m)


def metrics(eq: pd.Series, pos: pd.Series, trades: list[Trade]) -> dict:
    if len(eq) < 2:
        return {}
    ret = eq.pct_change().fillna(0.0)
    n = len(eq)
    years = n / 252
    total = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1 if years > 0 and eq.iloc[-1] > 0 else np.nan
    dd = eq / eq.cummax() - 1
    vol = ret.std() * np.sqrt(252)
    sharpe = (ret.mean() * 252 - 0.02) / vol if vol > 0 else np.nan
    downside = ret[ret < 0].std() * np.sqrt(252)
    sortino = (ret.mean() * 252 - 0.02) / downside if downside > 0 else np.nan
    wins = [t for t in trades if t.ret > 0]
    losses = [t for t in trades if t.ret <= 0]
    gp = sum(t.pnl for t in wins)
    gl = -sum(t.pnl for t in losses)
    return {
        "total_return_pct": total * 100,
        "cagr_pct": cagr * 100,
        "max_drawdown_pct": dd.min() * 100,
        "vol_annual_pct": vol * 100,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": (cagr / abs(dd.min())) if dd.min() < 0 else np.nan,
        "n_trades": len(trades),
        "win_rate_pct": len(wins) / len(trades) * 100 if trades else np.nan,
        "avg_win_pct": np.mean([t.ret for t in wins]) * 100 if wins else np.nan,
        "avg_loss_pct": np.mean([t.ret for t in losses]) * 100 if losses else np.nan,
        "profit_factor": gp / gl if gl > 0 else np.nan,
        "avg_hold_days": np.mean([t.hold_days for t in trades]) if trades else np.nan,
        "exposure_pct": (pos > 0.01).mean() * 100,
        "avg_position": pos.mean() * 100,
        "turnover_annual": pos.diff().abs().sum() / years if years > 0 else np.nan,
    }


def buy_hold(px: pd.DataFrame, window: slice | None = None) -> BacktestResult:
    """买入持有基准(全额、不加杠杆、含成本)。"""
    sub = px if window is None else px.loc[window]
    return backtest(sub, pd.Series(1.0, index=sub.index))
