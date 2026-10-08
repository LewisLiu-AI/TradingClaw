"""分层结构研究: 逐层确认每个组件是否真的加价值, 并在 IS/OOS 分别验证。

层:
  L1 趋势过滤  : 收盘 > MA_n 且 MA_n > MA_m  (基础多头暴露 = 收益引擎)
  L2 追踪止损  : 自持仓最高点回撤 x% (削减回撤)
  L3 抄底先手  : 趋势过滤为空仓时, 用 B 类信号先手建小仓 (抓 V 型底部)
  L4 派发减仓  : 过热/杠杆极端/大宗折价派发 -> 温和减仓(不清仓)
  L5 过热清仓  : (对照) 同上但清仓 —— 用于检验"过早下车"的代价
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import swing_lib as sl
import strategy as st

IS = ("2025-01-01", "2025-12-31")
OOS = ("2026-01-01", "2026-09-11")


def trend_only(df: pd.DataFrame, n: int = 20, m: int = 60) -> pd.Series:
    return ((df["close"] > df[f"ma{n}"]) & (df[f"ma{n}"] > df[f"ma{m}"])).astype(float)


def layered(df: pd.DataFrame, p: st.Params, *, trend: bool = True, trail: bool = True,
            dip: bool = False, derisk_trim: bool = False, derisk_exit: bool = False,
            ma_n: int = 20, ma_m: int = 60, cooldown: int = 0) -> pd.Series:
    """分层构造目标仓位(0~1), 返回 signal 序列(次日开盘执行)。"""
    sig = st.regime_and_heat(df, p)
    close = df["close"].to_numpy(float)
    base = trend_only(df, ma_n, ma_m).to_numpy() if trend else np.ones(len(df))
    dip_sig = sig["entry"].fillna(False).to_numpy()
    nd = sig["n_derisk"].fillna(0).to_numpy()
    dist = sig["D_distribute"].fillna(False).to_numpy()

    out = np.zeros(len(df))
    in_pos, peak, cd = False, 0.0, 0
    for i in range(len(df)):
        px = close[i]
        want = base[i]
        if want <= 0 and dip and dip_sig[i]:
            want = p.panic_size if in_pos is False else want
        if want <= 0 and in_pos and not trail:
            want = 0.0
        # 派发/过热处理
        if want > 0:
            if derisk_exit and (nd[i] >= 2 or dist[i]):
                want = 0.0
            elif derisk_trim:
                want *= (1.0 - 0.25 * (nd[i] == 1) - 0.45 * (nd[i] >= 2))
                if dist[i]:
                    want *= 0.7
        if in_pos:
            peak = max(peak, px)
            if trail and (px <= peak * (1 - p.trail_stop) or px <= peak * (1 - p.hard_stop)):
                want = 0.0
        if want > 0:
            if not in_pos:
                if cd > 0:
                    cd -= 1
                    want = 0.0
                else:
                    in_pos, peak = True, px
        else:
            if in_pos:
                in_pos, peak, cd = False, 0.0, cooldown
        out[i] = want
    return pd.Series(out, index=df.index, name="target")


def _m(name: str, pos: pd.Series, sub: pd.DataFrame) -> dict:
    mm = sl.backtest(sub, pos.reindex(sub.index)).metrics
    return {"variant": name, "ret%": mm["total_return_pct"], "cagr%": mm["cagr_pct"],
            "mdd%": mm["max_drawdown_pct"], "sharpe": mm["sharpe"],
            "calmar": mm["calmar"], "expo%": mm["exposure_pct"], "n": mm["n_trades"]}


def main() -> None:
    df = sl.add_features(sl.load_panel()).replace([np.inf, -np.inf], np.nan)
    p = st.Params()

    print("=" * 100)
    print("A. 趋势过滤的参数结构 (只比较结构, 不做微调; 样本内选定, 样本外检验)")
    print("=" * 100)
    rows = []
    for label, (a, b) in (("IS", IS), ("OOS", OOS)):
        sub = df.loc[a:b]
        for n, m in ((10, 30), (10, 60), (20, 60), (20, 120), (30, 60), (30, 120), (60, 120)):
            for tr in (0.0, 0.18, 0.25):
                pos = layered(df, p, trail=tr > 0, ma_n=n, ma_m=m)
                if tr:
                    pos = layered(df, p, trail=True, ma_n=n, ma_m=m)
                else:
                    pos = trend_only(df, n, m)
                r = _m(f"MA{n}/{m}" + (f"+追踪{tr:.0%}" if tr else ""), pos, sub)
                r["窗口"] = label
                rows.append(r)
    t = pd.DataFrame(rows)
    piv = t.pivot_table(index="variant", columns="窗口",
                        values=["ret%", "mdd%", "sharpe", "calmar"]).round(2)
    print(piv.to_string())

    print("\n" + "=" * 100)
    print("B. 逐层叠加 (MA20/60 + 18%追踪 之上加 L3/L4/L5)")
    print("=" * 100)
    variants = {
        "L1 趋势(MA20/60)": dict(trend=True, trail=False),
        "L1+L2 趋势+追踪18%": dict(trend=True, trail=True),
        "L1+L2+L3 加抄底先手": dict(trend=True, trail=True, dip=True),
        "L1+L2+L4 加派发减仓": dict(trend=True, trail=True, derisk_trim=True),
        "L1+L2+L3+L4 (全)": dict(trend=True, trail=True, dip=True, derisk_trim=True),
        "L1+L2+L5 过热即清仓": dict(trend=True, trail=True, derisk_exit=True),
        "仅 L2 满仓+追踪": dict(trend=False, trail=True),
    }
    rows = []
    for label, (a, b) in (("IS", IS), ("OOS", OOS), ("全样本", ("2024-06-01", "2026-09-11"))):
        sub = df.loc[a:b]
        rows.append({**_m("买入持有", pd.Series(1.0, index=df.index), sub), "窗口": label})
        for name, kw in variants.items():
            rows.append({**_m(name, layered(df, p, **kw), sub), "窗口": label})
    t2 = pd.DataFrame(rows)
    for win in t2["窗口"].unique():
        print(f"\n--- {win} ---")
        print(t2[t2["窗口"] == win].drop(columns="窗口").round(2).to_string(index=False))

    print("\n" + "=" * 100)
    print("C. 抄底先手(L3)单独贡献: 只在趋势空仓日入场")
    print("=" * 100)
    for label, (a, b) in (("IS", IS), ("OOS", OOS)):
        sub = df.loc[a:b]
        print(f"\n--- {a} ---")
        print(pd.DataFrame([_m("L1+L2", layered(df, p, trend=True, trail=True), sub),
                            _m("L1+L2+L3", layered(df, p, trend=True, trail=True, dip=True), sub)]
                           ).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
