"""跨资产 / 海外宏观因子 能否帮助决策?

补上第 11 节缺失的一块: 第 11 节用的全是 A 股本土变量(创业板指量价 + 宽基风格 + 沪市两融),
本次加入 黄金/原油/美债10Y/美元指数/VIX/费城半导体/纳斯达克/铜, 以及北向成交额。

时序合规性(重要): 美股在 T 日 16:00 ET 收盘 = 北京时间 T+1 凌晨, 因此
**美股 T 日数据在中国 T+1 开盘前已知**, 用于中国 T+1 的交易决策完全无前视。
相比之下 A 股自身 T 日数据要在 T 日收盘后才知道 —— 所以海外因子的时序甚至更宽松。

被解释变量(与第 11 节一致, 可直接对比):
  A. 先手贡献 = 月度收益(先手开) - 月度收益(先手关)   ← 判断"该不该做抄底先手"
  B. 策略月收益(推荐配置)                            ← 判断"该不该交易"
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf

import analyze_macro as am
import cross_check as cc
import swing_lib as sl
import tune_trend as tt

pd.set_option("display.width", 250)
CACHE = "data/global"
GLOBAL = {
    "GC=F": ("gold", "黄金"), "CL=F": ("oil", "WTI原油"), "^TNX": ("us10y", "美债10Y"),
    "DX-Y.NYB": ("dxy", "美元指数"), "^VIX": ("vix", "VIX"), "^SOX": ("sox", "费城半导体"),
    "^IXIC": ("ixic", "纳斯达克"), "HG=F": ("copper", "铜"), "^HSI": ("hsi", "恒生指数"),
}


def load_global() -> pd.DataFrame:
    import pathlib
    pathlib.Path(CACHE).mkdir(parents=True, exist_ok=True)
    out = {}
    for sym, (tag, name) in GLOBAL.items():
        f = f"{CACHE}/{tag}.csv"
        try:
            d = pd.read_csv(f, parse_dates=["date"]).set_index("date")["close"]
        except Exception:  # noqa: BLE001
            d = None
        if d is None or len(d) == 0:
            try:
                raw = yf.download(sym, start="2023-06-01", end="2026-09-13",
                                  progress=False, auto_adjust=True)
                d = raw["Close"].dropna()
                d = d.iloc[:, 0] if isinstance(d, pd.DataFrame) else d
                d.index.name = "date"
                d.to_frame("close").to_csv(f, encoding="utf-8-sig")
            except Exception as exc:  # noqa: BLE001
                print(f"  {name} 抓取失败: {type(exc).__name__}")
                continue
        out[name] = d.rename(name)
        print(f"  {name:8s} {len(d):4d} 行 {d.index.min().date()}..{d.index.max().date()}")
    g = pd.concat(out.values(), axis=1).sort_index()
    return g


def global_features(g: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=g.index)
    for c in g.columns:
        if c == "VIX":
            f["VIX_水平"] = g[c]
            f["VIX_20日变化%"] = g[c].pct_change(20) * 100
        elif c == "美债10Y":
            f["美债10Y_水平"] = g[c]
            f["美债10Y_20日变化bp"] = (g[c] - g[c].shift(20)) * 100
        else:
            f[f"{c}_20日变化%"] = g[c].pct_change(20) * 100
            f[f"{c}_距60日高点%"] = (g[c] / g[c].rolling(60).max() - 1) * 100
    f["SOX/纳指_相对强弱20日"] = f.get("费城半导体_20日变化%", 0) - f.get("纳斯达克_20日变化%", 0)
    f["黄金/原油比_20日变化%"] = ((g["黄金"] / g["WTI原油"]).pct_change(20) * 100)
    f["VIX_距60日低点"] = (g["VIX"] / g["VIX"].rolling(60).min() - 1) * 100
    return f


def test(p: pd.DataFrame, feats: list, ycol: str, label: str) -> pd.DataFrame:
    rows = []
    for c in feats:
        if c not in p.columns:
            continue
        x, y = p[c].astype(float), p[ycol].astype(float)
        ok = x.notna() & y.notna()
        if ok.sum() < 100 or x[ok].nunique() < 3:
            continue
        med = x[ok].median()
        hi, lo = y[ok][x[ok] > med].to_numpy(), y[ok][x[ok] <= med].to_numpy()
        rng = np.random.default_rng(7)
        obs = hi.mean() - lo.mean()
        pool = np.concatenate([hi, lo])
        cnt = sum(1 for _ in range(3000)
                  if (lambda s: s[:len(hi)].mean() - s[len(hi):].mean())(rng.permutation(pool)) >= obs)
        p25 = p[p["月份"] <= "2025-12"]
        p26 = p[p["月份"] >= "2026-01"]
        def diff(sub):
            xx, yy = sub[c].astype(float), sub[ycol].astype(float)
            m = xx.notna() & yy.notna()
            if m.sum() < 40 or xx[m].nunique() < 2:
                return np.nan
            md = xx[m].median()
            return yy[m][xx[m] > md].mean() - yy[m][xx[m] <= md].mean()
        rows.append({"变量": c, "高组%": hi.mean(), "低组%": lo.mean(), "差异pp": obs,
                     "p值": cnt / 3000, "2025": diff(p25), "2026": diff(p26),
                     "Spearman": x[ok].corr(y[ok], method="spearman")})
    t = pd.DataFrame(rows).sort_values("p值")
    t["同向"] = np.where(np.sign(t["2025"]) == np.sign(t["2026"]), "是", "否")
    print(f"\n=== {label} ===")
    print(t.round(3).to_string(index=False))
    return t


def main() -> None:
    print("抓取跨资产数据 ...")
    g = load_global()
    gf = global_features(g)

    panel = pd.read_csv("results_macro_panel.csv")
    mkt = am.load_market()

    # 月度化: 用"上月末"取值(PIT)
    gf_m = gf.copy()
    gf_m.index = gf_m.index + pd.offsets.MonthEnd(1)
    gf_m = gf_m[~gf_m.index.duplicated(keep="last")]
    mk_m = mkt.copy()
    mk_m.index = mk_m.index + pd.offsets.MonthEnd(1)
    mk_m = mk_m[~mk_m.index.duplicated(keep="last")]

    panel["_mend"] = pd.to_datetime(panel["月份"] + "-01") + pd.offsets.MonthEnd(0)
    panel = panel.merge(gf_m, left_on="_mend", right_index=True, how="left")
    panel = panel.merge(mk_m[["mkt_amt_ratio", "mkt_ret20", "mkt_vol20", "mkt_margin_chg20"]],
                        left_on="_mend", right_index=True, how="left", suffixes=("", "_cn"))

    # 策略月收益(推荐配置, 口径 B)
    print("\n构建策略月收益(推荐配置) ...")
    idx = pd.read_csv("data/idx_cyb.csv", parse_dates=["date"]).set_index("date")["close"]
    srows = []
    for code, sym, name in am.SYMBOLS:
        d = cc.fetch_peer(sym)
        if d is None or len(d) < 250:
            continue
        feat = sl.add_features(cc.prep(d).assign(idx_cyb=idx.reindex(d.index).ffill()))
        feat = feat.replace([np.inf, -np.inf], np.nan)
        pos = tt.banded_trend(feat, buy_band=0.05, sell_band=0.05, dip=True)
        eq = sl.backtest(feat, pos).equity
        mon = (1 + eq.pct_change().fillna(0)).resample("ME").prod() - 1
        for dt in mon.index:
            ms = dt - pd.offsets.MonthBegin(1)
            if dt < pd.Timestamp("2025-01-01") or ms > pd.Timestamp("2026-09-11"):
                continue
            srows.append({"标的": name, "月份": dt.to_period("M").strftime("%Y-%m"),
                          "策略月收益%": mon.loc[dt] * 100})
    smon = pd.DataFrame(srows)
    panel = panel.merge(smon, on=["标的", "月份"], how="left")

    global_feats = [c for c in gf.columns]
    cn_feats = ["mkt_amt_ratio", "mkt_ret20", "mkt_vol20", "mkt_margin_chg20"]

    print("\n" + "=" * 118)
    print("对照基准: 第 11 节的 A 股本土变量(先手贡献)")
    print("=" * 118)
    t_cn = test(panel, cn_feats, "先手贡献%", "A股本土变量")

    print("\n" + "=" * 118)
    print("新增: 跨资产/海外因子")
    print("=" * 118)
    t_gl = test(panel, global_feats, "先手贡献%", "跨资产/海外因子 → 先手贡献")

    print("\n" + "=" * 118)
    print("口径 B: 跨资产因子 → 策略月收益(推荐配置)")
    print("=" * 118)
    t_b = test(panel, global_feats + cn_feats, "策略月收益%", "跨资产+本土 → 策略月收益")

    both = pd.concat([t_cn.assign(类别="A股本土"), t_gl.assign(类别="跨资产")])
    both = both.sort_values("p值")
    print("\n" + "=" * 118)
    print("合并排名: 谁的区分力最强 (p值排序, 只看样本内外同向的)")
    print("=" * 118)
    print(both[both["同向"] == "是"].head(14)[
        ["类别", "变量", "差异pp", "p值", "2025", "2026", "Spearman"]].round(3).to_string(index=False))
    print("\n多重检验提示: 本次共检验", len(both), "个变量, 偶然期望约",
          round(len(both) * 0.05, 1), "个达到 p<0.05")

    panel.to_csv("results_global_panel.csv", index=False, encoding="utf-8-sig")
    both.to_csv("results_global_separation.csv", index=False, encoding="utf-8-sig")
    print("\n-> results_global_panel.csv / results_global_separation.csv")


if __name__ == "__main__":
    main()
