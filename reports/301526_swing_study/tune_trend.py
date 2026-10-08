"""趋势层抗震荡优化: 进出场滞回带 + 组合各层, 观察 IS/OOS 是否一致。

动机: 2025 年该股反复 -13%~-35% 震荡, 纯 "收盘>MA20" 规则被反复打脸(whipsaw)。
滞回带(进场要求高于均线 x%, 离场容忍跌破均线 y%)是经典抗震荡手段, 只引入 2 个参数。

输出完整网格而非单一最优点, 用于判断稳健区域是否存在。
"""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

import swing_lib as sl
import strategy as st
import layers as ly

IS = ("2025-01-01", "2025-12-31")
OOS = ("2026-01-01", "2026-09-11")
FULL = ("2024-06-01", "2026-09-11")


def banded_trend(df: pd.DataFrame, *, ma_n: int = 20, ma_m: int = 60,
                 buy_band: float = 0.0, sell_band: float = 0.0,
                 require_cross: bool = True, trail: float = 0.0,
                 dip: bool = False, derisk_trim: float = 0.0,
                 derisk_exit: bool = False, p: st.Params | None = None) -> pd.Series:
    """滞回带趋势状态机。

    flat -> long : close > ma_n*(1+buy_band) 且 (若 require_cross) ma_n > ma_m
    long -> flat : close < ma_n*(1-sell_band) 或 (若 require_cross) ma_n < ma_m
    中间地带保持原状态(滞回)。

    derisk_trim > 0 : 过热/杠杆极端/大宗派发时把仓位乘以 (1-derisk_trim)
    derisk_exit     : 同上但直接清仓(对照组)
    """
    p = p or st.Params()
    ma_n_s, ma_m_s = df[f"ma{ma_n}"], df[f"ma{ma_m}"]
    c = df["close"]
    up_ok = (c > ma_n_s * (1 + buy_band)) & ((ma_n_s > ma_m_s) if require_cross else True)
    dn_ok = (c < ma_n_s * (1 - sell_band)) | ((ma_n_s < ma_m_s) if require_cross else False)
    sig = st.regime_and_heat(df, p) if (dip or derisk_trim or derisk_exit) else None
    dip_sig = sig["entry"].fillna(False).to_numpy() if dip else None
    nd = sig["n_derisk"].fillna(0).to_numpy() if sig is not None else None
    dist = sig["D_distribute"].fillna(False).to_numpy() if sig is not None else None

    close = c.to_numpy(float)
    upv, dnv = up_ok.to_numpy(bool), dn_ok.to_numpy(bool)
    out = np.zeros(len(df))
    in_pos, peak = False, 0.0
    for i in range(len(df)):
        px = close[i]
        if in_pos:
            peak = max(peak, px)
            risky = derisk_exit and nd is not None and (nd[i] >= 2 or dist[i])
            if dnv[i] or risky or (trail > 0 and px <= peak * (1 - trail)):
                in_pos = False
                out[i] = 0.0
                continue
            w = 1.0
            if derisk_trim > 0 and nd is not None:
                w *= (1.0 - 0.5 * derisk_trim) if nd[i] >= 2 else (
                    (1.0 - 0.25 * derisk_trim) if nd[i] == 1 else 1.0)
                if dist[i]:
                    w *= (1.0 - derisk_trim)
            out[i] = w
        else:
            if upv[i]:
                in_pos, peak, out[i] = True, px, 1.0
            elif dip and dip_sig[i]:
                in_pos, peak, out[i] = True, px, p.panic_size
            else:
                out[i] = 0.0
    return pd.Series(out, index=df.index, name="target")


def metrics_for(pos: pd.Series, sub: pd.DataFrame) -> dict:
    m = sl.backtest(sub, pos.reindex(sub.index)).metrics
    return {"ret%": m["total_return_pct"], "mdd%": m["max_drawdown_pct"],
            "sharpe": m["sharpe"], "calmar": m["calmar"], "expo%": m["exposure_pct"]}


def main() -> None:
    df = sl.add_features(sl.load_panel()).replace([np.inf, -np.inf], np.nan)
    wins = {"IS": df.loc[IS[0]:IS[1]], "OOS": df.loc[OOS[0]:OOS[1]],
            "FULL": df.loc[FULL[0]:FULL[1]]}
    bh = {k: metrics_for(pd.Series(1.0, index=df.index), v) for k, v in wins.items()}
    print("基准 买入持有:", {k: f"{v['ret%']:.0f}%/{v['mdd%']:.0f}%/{v['sharpe']:.2f}"
                             for k, v in bh.items()})

    print("\n" + "=" * 110)
    print("A. 滞回带网格 (MA20/60基础, 无追踪止损). 单元格 = IS收益 / OOS收益 / FULL_Calmar")
    print("=" * 110)
    grid = list(itertools.product([0.0, 0.02, 0.03, 0.05], [0.0, 0.02, 0.03, 0.05]))
    rows = []
    for bb, sb in grid:
        pos = banded_trend(df, buy_band=bb, sell_band=sb)
        r = {"买带": bb, "卖带": sb}
        for k, sub in wins.items():
            mm = metrics_for(pos, sub)
            r[f"{k}_ret"] = mm["ret%"]
            r[f"{k}_mdd"] = mm["mdd%"]
            r[f"{k}_calmar"] = mm["calmar"]
            r[f"{k}_sharpe"] = mm["sharpe"]
        rows.append(r)
    t = pd.DataFrame(rows)
    show = t[["买带", "卖带", "IS_ret", "IS_mdd", "OOS_ret", "OOS_mdd",
              "FULL_ret", "FULL_mdd", "FULL_calmar", "FULL_sharpe"]]
    print(show.round(2).to_string(index=False))

    print("\n" + "=" * 110)
    print("B. 在滞回带之上叠加 抄底先手(仅空仓时) / 追踪止损, 看 IS 与 OOS 是否同向")
    print("=" * 110)
    variants = []
    for bb, sb in ((0.0, 0.0), (0.03, 0.0), (0.03, 0.03), (0.05, 0.03)):
        variants.append((f"走势带({bb:.0%}/{sb:.0%})", dict(buy_band=bb, sell_band=sb)))
        variants.append((f"走势带({bb:.0%}/{sb:.0%})+抄底", dict(buy_band=bb, sell_band=sb, dip=True)))
        variants.append((f"走势带({bb:.0%}/{sb:.0%})+追踪18%", dict(buy_band=bb, sell_band=sb, trail=0.18)))
        variants.append((f"走势带({bb:.0%}/{sb:.0%})+抄底+追踪18%",
                         dict(buy_band=bb, sell_band=sb, dip=True, trail=0.18)))
    rows = []
    for name, kw in variants:
        pos = banded_trend(df, **kw)
        r = {"variant": name}
        for k, sub in wins.items():
            mm = metrics_for(pos, sub)
            r[f"{k}_ret"] = mm["ret%"]
            r[f"{k}_mdd"] = mm["mdd%"]
            r[f"{k}_sharpe"] = mm["sharpe"]
            r[f"{k}_calmar"] = mm["calmar"]
        rows.append(r)
    t2 = pd.DataFrame(rows)
    print(t2.round(2).to_string(index=False))

    print("\n" + "=" * 110)
    print("C. 均线对选择 (滞回带 3%/0%, 加抄底先手)")
    print("=" * 110)
    rows = []
    for n, m in ((10, 30), (10, 60), (20, 60), (20, 120), (30, 60), (30, 120), (60, 120)):
        pos = banded_trend(df, ma_n=n, ma_m=m, buy_band=0.03, sell_band=0.0, dip=True)
        r = {"均线": f"MA{n}/{m}"}
        for k, sub in wins.items():
            mm = metrics_for(pos, sub)
            r[f"{k}_ret"] = mm["ret%"]
            r[f"{k}_mdd"] = mm["mdd%"]
            r[f"{k}_calmar"] = mm["calmar"]
        rows.append(r)
    print(pd.DataFrame(rows).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
