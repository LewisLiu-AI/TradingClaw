"""可迁移性检验: 这套规则能用到别的股票上吗, 还是 301526 定制?

两种"可迁移"路线对比(19 只 A 股 AI/科技链高波动标的, 同一窗口 2024-06~2026-09):
  FIX  固定百分比版: MA20/60 + 买带5%/卖带5% (+可选18%追踪) —— 阈值与个股波动率无关
  ATR  ATR自适应版 : 买带 = k x ATR%, 卖带 = k x ATR%, 追踪止损 = m x ATR%
                     (ATR% 取 60 日中位数, PIT 可得) —— 阈值随个股自身波动率缩放

判据:
  - 若 ATR 版在多数标的上同时改善 回撤 与 Calmar -> 规则可迁移(只是需要波动率归一化)
  - 若只有 FIX 版在 301526 上表现突出, 其他标的普遍大幅跑输 -> 属于定制
另外报告"捕获率"(策略收益 / 买入持有收益)的中位数, 这是可迁移性的核心指标。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import cross_check as cc
import swing_lib as sl

pd.set_option("display.width", 250)
START, END = "2024-06-01", "2026-09-11"

# 扩充样本: 在原 8 只基础上再加 12 只 AI/科技链高波动标的(含光模块/半导体/PCB)
EXTRA = [
    ("300502", "sz300502", "新易盛"), ("002281", "sz002281", "光迅科技"),
    ("002916", "sz002916", "深南电路"), ("688008", "sh688008", "澜起科技"),
    ("688041", "sh688041", "海光信息"), ("603986", "sh603986", "兆易创新"),
    ("603501", "sh603501", "韦尔股份"), ("600584", "sh600584", "长电科技"),
    ("002156", "sz002156", "通富微电"), ("605358", "sh605358", "立昂微"),
    ("300476", "sz300476", "胜宏科技"), ("300223", "sz300223", "北京君正"),
]


def all_symbols() -> list:
    out, seen = [], set()
    for item in cc.PEERS + EXTRA:
        if item[2].startswith("沪深") or item[0] in seen:
            continue
        seen.add(item[0])
        out.append(item)
    return out


def atr_series(df: pd.DataFrame, n: int = 14, med: int = 60) -> pd.Series:
    """ATR% 的滚动中位数(PIT, 只用过去数据) —— 个股自身的波动率标尺。"""
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean() / c * 100
    return atr.rolling(med).median().shift(1)      # shift(1): 严格用昨日及之前


def trend_band_atr(df: pd.DataFrame, atr_pct: pd.Series, k: float,
                   trail_mult: float = 0.0) -> pd.Series:
    """ATR 自适应滞回带趋势: 买带/卖带/止损全部按个股自身 ATR% 缩放。"""
    c, ma20, ma60 = df["close"], df["ma20"], df["ma60"]
    band = (k * atr_pct / 100).clip(0.01, 0.30).fillna(0.05)
    up = (c > ma20 * (1 + band)) & (ma20 > ma60)
    dn = (c < ma20 * (1 - band)) | (ma20 < ma60)
    trail = (trail_mult * atr_pct / 100).clip(0.05, 0.60).fillna(0.18) if trail_mult else None
    cn, upv, dnv = c.to_numpy(float), up.to_numpy(bool), dn.to_numpy(bool)
    tv = trail.to_numpy(float) if trail is not None else None
    out, s, peak = np.zeros(len(df)), False, 0.0
    for i in range(len(df)):
        if s:
            peak = max(peak, cn[i])
            if dnv[i] or (tv is not None and cn[i] <= peak * (1 - tv[i])):
                s = False
                continue
            out[i] = 1.0
        elif upv[i]:
            s, peak, out[i] = True, cn[i], 1.0
    return pd.Series(out, index=df.index)


def trend_band_fixed(df: pd.DataFrame, band: float = 0.05,
                     trail: float = 0.0) -> pd.Series:
    c, ma20, ma60 = df["close"], df["ma20"], df["ma60"]
    up = (c > ma20 * (1 + band)) & (ma20 > ma60)
    dn = (c < ma20 * (1 - band)) | (ma20 < ma60)
    cn, upv, dnv = c.to_numpy(float), up.to_numpy(bool), dn.to_numpy(bool)
    out, s, peak = np.zeros(len(df)), False, 0.0
    for i in range(len(df)):
        if s:
            peak = max(peak, cn[i])
            if dnv[i] or (trail and cn[i] <= peak * (1 - trail)):
                s = False
                continue
            out[i] = 1.0
        elif upv[i]:
            s, peak, out[i] = True, cn[i], 1.0
    return pd.Series(out, index=df.index)


def trail_only(df: pd.DataFrame, trail: float = 0.0, atr_pct: pd.Series | None = None,
               atr_mult: float = 0.0) -> pd.Series:
    """不设趋势过滤: 满仓持有 + 追踪止损(固定% 或 n x ATR%), 止损后次日无条件回补。"""
    c = df["close"]
    cn = c.to_numpy(float)
    tv = None
    if atr_mult and atr_pct is not None:
        tv = (atr_mult * atr_pct / 100).clip(0.05, 0.60).fillna(0.25).to_numpy(float)
    out, s, peak = np.zeros(len(df)), False, 0.0
    for i in range(len(df)):
        if s:
            peak = max(peak, cn[i])
            t = tv[i] if tv is not None else trail
            if cn[i] <= peak * (1 - t):
                s = False
                continue
            out[i] = 1.0
        else:
            s, peak, out[i] = True, cn[i], 1.0
    return pd.Series(out, index=df.index)


def stat(df: pd.DataFrame, pos: pd.Series) -> dict:
    m = sl.backtest(df, pos).metrics
    return {"收益%": m["total_return_pct"], "回撤%": m["max_drawdown_pct"],
            "Sharpe": m["sharpe"], "Calmar": m["calmar"], "交易数": m["n_trades"],
            "在场%": m["exposure_pct"]}


def main() -> None:
    syms = all_symbols()
    print(f"样本: {len(syms)} 只标的, 窗口 {START}~{END}\n")

    data = {}
    for code, sym, name in syms:
        d = cc.fetch_peer(sym)
        if d is None or len(d) < 250:
            print(f"  {name}: 数据不足, 跳过")
            continue
        feat = cc.prep(d).replace([np.inf, -np.inf], np.nan)
        feat["atr_pct_med"] = atr_series(feat)
        data[name] = feat
    print(f"可用: {len(data)} 只\n")

    rows = []
    for name, f in data.items():
        bh = stat(f, pd.Series(1.0, index=f.index))
        atrp = f["atr_pct_med"]
        variants = {
            "买入持有": pd.Series(1.0, index=f.index),
            "FIX 买带5/卖带5": trend_band_fixed(f, 0.05, 0.0),
            "FIX 买带5/卖带5+追踪18%": trend_band_fixed(f, 0.05, 0.18),
            "ATR k=0.6 无追踪": trend_band_atr(f, atrp, 0.6, 0.0),
            "ATR k=0.6 追踪2.0xATR": trend_band_atr(f, atrp, 0.6, 2.0),
            "ATR k=1.0 追踪2.0xATR": trend_band_atr(f, atrp, 1.0, 2.0),
            "ATR k=0.4 追踪1.5xATR": trend_band_atr(f, atrp, 0.4, 1.5),
            "满仓+25%追踪(无趋势过滤)": trail_only(f, 0.25),
            "满仓+2.5xATR追踪": trail_only(f, 0.0, atrp, 2.5),
        }
        for vn, pos in variants.items():
            s = stat(f, pos)
            s.update({"标的": name, "变体": vn, "ATR%中位": float(atrp.median()) if atrp.notna().any() else np.nan})
            rows.append(s)
    t = pd.DataFrame(rows)
    bh = t[t["变体"] == "买入持有"].set_index("标的")

    print("=" * 132)
    print("1. 汇总: 各变体的中位数与改善广度")
    print("=" * 132)
    out = []
    for vn in t["变体"].unique():
        s = t[t["变体"] == vn].set_index("标的")
        j = s.join(bh, rsuffix="_bh")
        out.append({
            "变体": vn,
            "中位收益%": s["收益%"].median(), "中位回撤%": s["回撤%"].median(),
            "中位Sharpe": s["Sharpe"].median(), "中位Calmar": s["Calmar"].median(),
            "捕获率(收益/BH)中位": (j["收益%"] / j["收益%_bh"]).median(),
            "回撤改善": f"{(j['回撤%'] > j['回撤%_bh']).sum()}/{len(j)}",
            "收益改善": f"{(j['收益%'] > j['收益%_bh']).sum()}/{len(j)}",
            "Calmar改善": f"{(j['Calmar'] > j['Calmar_bh']).sum()}/{len(j)}",
            "Sharpe改善": f"{(j['Sharpe'] > j['Sharpe_bh']).sum()}/{len(j)}",
        })
    res = pd.DataFrame(out)
    print(res.round(2).to_string(index=False))

    print("\n" + "=" * 132)
    print("2. 逐标的: 捕获率(策略收益/买入持有收益) —— 可迁移性的核心指标")
    print("=" * 132)
    piv = t.pivot_table(index="标的", columns="变体", values="收益%")
    cap = piv.div(piv["买入持有"], axis=0)
    atr_med = t.groupby("标的")["ATR%中位"].first()
    show = cap.drop(columns=["买入持有"]).join(atr_med).round(2)
    show = show.sort_values("ATR%中位", ascending=False)
    print(show.to_string())
    print("\n捕获率 >1 表示跑赢买入持有; 中位数 <1 表示多数标的跑输。")

    print("\n" + "=" * 132)
    print("3. 波动率越高是否越需要 ATR 自适应? (按 ATR% 中位数分两组)")
    print("=" * 132)
    hi = show[show["ATR%中位"] > show["ATR%中位"].median()].index
    lo = show.index.difference(hi)
    for vn in ["FIX 买带5/卖带5", "FIX 买带5/卖带5+追踪18%", "ATR k=0.6 追踪2.0xATR"]:
        print(f"  {vn:26s} 高波动组捕获率中位 {show.loc[hi, vn].median():.2f} | "
              f"低波动组 {show.loc[lo, vn].median():.2f}")

    t.to_csv("results_portability.csv", index=False, encoding="utf-8-sig")
    res.to_csv("results_portability_summary.csv", index=False, encoding="utf-8-sig")
    cap.to_csv("results_portability_capture.csv", encoding="utf-8-sig")
    print("\n-> results_portability*.csv")


if __name__ == "__main__":
    main()
