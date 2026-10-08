"""宏观/市场状态能否过滤掉"无效交易月"?

思路(避免 n=21 个月的单标的过拟合):
  面板 = 9 只股票 x 21 个月 (2025-01~2026-09) ≈ 189 个"股票-月"。
  被解释变量 = 本月「抄底先手层」的贡献 = 月度收益(先手开) - 月度收益(先手关)。
  解释变量 = 上月末即可观测的**市场层面**状态(所有股票共享) + 个股自身状态(对照)。

  若某个市场变量能事前区分"先手有效/无效", 就可以做成 gate 过滤掉无效交易。

用法: python analyze_macro.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import cross_check as cc
import signal_engine as se
import swing_lib as sl
import tune_trend as tt

pd.set_option("display.width", 240)
START, END = "2024-06-01", "2026-09-11"
STUDY = ("2025-01-01", "2026-09-11")


# ─────────────────────── 数据准备 ───────────────────────

def load_market() -> pd.DataFrame:
    """市场层面状态(所有股票共享), 全部为 PIT 可得。"""
    def rd(name: str, datecol: str = "date") -> pd.DataFrame:
        d = pd.read_csv(f"data/{name}.csv")
        d = d.rename(columns={datecol: "date"})
        d["date"] = pd.to_datetime(d["date"])
        return d.set_index("date").sort_index()

    cyb = rd("idx_cyb")
    hs300 = rd("idx_hs300")
    zz500 = rd("mkt_csi500")
    sse50 = rd("mkt_sse50")
    marg = rd("mkt_margin")

    m = pd.DataFrame(index=cyb.index)
    c = cyb["close"]
    # 市场趋势与动量
    m["mkt_close"] = c
    m["mkt_ma20"] = c.rolling(20).mean()
    m["mkt_ma60"] = c.rolling(60).mean()
    m["mkt_above_ma20"] = (c > m["mkt_ma20"]).astype(int)
    m["mkt_ma20_gt_ma60"] = (m["mkt_ma20"] > m["mkt_ma60"]).astype(int)
    m["mkt_ret5"] = c.pct_change(5) * 100
    m["mkt_ret20"] = c.pct_change(20) * 100
    m["mkt_ret60"] = c.pct_change(60) * 100
    m["mkt_dd60"] = (c / c.rolling(60).max() - 1) * 100
    m["mkt_dd120"] = (c / c.rolling(120).max() - 1) * 100
    # 市场波动率(年化, 20日已实现)
    m["mkt_vol20"] = c.pct_change().rolling(20).std() * np.sqrt(252) * 100
    m["mkt_vol60"] = c.pct_change().rolling(60).std() * np.sqrt(252) * 100
    m["mkt_vol_ratio"] = m["mkt_vol20"] / m["mkt_vol60"]
    # 市场活跃度(新浪兜底的指数数据只有成交量, 用成交量作代理)
    m["mkt_amt"] = cyb["volume"]
    m["mkt_amt_ratio"] = cyb["volume"].rolling(5).mean() / cyb["volume"].rolling(20).mean()
    # 风格: 小盘 vs 大盘
    for tag, d in (("zz500", zz500), ("sse50", sse50), ("hs300", hs300)):
        m[f"_{tag}"] = d["close"].reindex(m.index).ffill()
    m["style_small_big"] = (m["_zz500"] / m["_sse50"]).pct_change(20) * 100
    m["style_growth_value"] = (m["mkt_close"] / m["_hs300"]).pct_change(20) * 100
    # 全市场杠杆
    # 注: akshare 的深市两融数据在 2024-06~2025-06 系统性缺失(177 个交易日),
    #     因此使用**沪市单边**序列(完整 653 天, 占全市场约 51%)作为市场杠杆代理。
    m["mkt_margin"] = marg["mkt_rz_balance_sh"].reindex(m.index).ffill()
    m["mkt_margin_chg20"] = m["mkt_margin"].pct_change(20) * 100
    m["mkt_margin_z"] = ((m["mkt_margin"] - m["mkt_margin"].rolling(120).mean())
                        / m["mkt_margin"].rolling(120).std())
    return m.drop(columns=[c for c in m.columns if c.startswith("_")])


def stock_position(df: pd.DataFrame, with_dip: bool) -> pd.Series:
    return tt.banded_trend(df, buy_band=0.05, sell_band=0.05, dip=with_dip)


def _symbols() -> list:
    """cc.PEERS 里已含 301526, 去重且剔除指数对照。"""
    out, seen = [], set()
    for item in cc.PEERS:
        if item[2].startswith("沪深") or item[0] in seen:
            continue
        seen.add(item[0])
        out.append(item)
    return out


SYMBOLS = _symbols()


def build_stock_month_panel() -> pd.DataFrame:
    idx = pd.read_csv("data/idx_cyb.csv", parse_dates=["date"]).set_index("date")["close"]
    rows = []
    for code, sym, name in SYMBOLS:
        d = cc.fetch_peer(sym)
        if d is None or len(d) < 200:
            continue
        d = cc.prep(d)
        d = d.assign(idx_cyb=idx.reindex(d.index).ffill())
        try:
            feat = sl.add_features(d)
        except Exception as exc:  # noqa: BLE001
            print(f"  {name} 特征失败: {exc}")
            continue
        feat = feat.replace([np.inf, -np.inf], np.nan)
        pos_on = stock_position(feat, True)
        pos_off = stock_position(feat, False)
        eq_on = sl.backtest(feat, pos_on).equity
        eq_off = sl.backtest(feat, pos_off).equity
        # 交易笔数(按信号变化计)
        n_sig = int((pos_on.diff().abs() > 1e-9).sum())
        mon_on = (1 + eq_on.pct_change().fillna(0)).resample("ME").prod() - 1
        mon_off = (1 + eq_off.pct_change().fillna(0)).resample("ME").prod() - 1
        bh = (1 + feat["close"].pct_change().fillna(0)).resample("ME").prod() - 1
        tgt_on = pos_on.resample("ME").last()
        nsig_m = pos_on.diff().abs().gt(1e-9).resample("ME").sum()
        for dt in mon_on.index:
            month_start = dt - pd.offsets.MonthBegin(1)
            if dt < pd.Timestamp(STUDY[0]) or month_start > pd.Timestamp(STUDY[1]):
                continue   # 保留不完整月(如 2026-09 只到 09-11)
            rows.append({
                "标的": name, "月份": dt.to_period("M").strftime("%Y-%m"),
                "月收益_先手开%": mon_on.loc[dt] * 100,
                "月收益_先手关%": mon_off.loc[dt] * 100,
                "月收益_持有%": bh.loc[dt] * 100,
                "先手贡献%": (mon_on.loc[dt] - mon_off.loc[dt]) * 100,
                "月末仓位": tgt_on.loc[dt], "信号次数": int(nsig_m.loc[dt]),
                "_n": n_sig,
            })
    return pd.DataFrame(rows)


# ─────────────────────── 分析 ───────────────────────

MKT_FEATS = ["mkt_above_ma20", "mkt_ma20_gt_ma60", "mkt_ret5", "mkt_ret20", "mkt_ret60",
             "mkt_dd60", "mkt_dd120", "mkt_vol20", "mkt_vol_ratio", "mkt_amt_ratio",
             "style_small_big", "style_growth_value", "mkt_margin_chg20", "mkt_margin_z"]


def main() -> None:
    print("构建股票-月面板 ...")
    panel = build_stock_month_panel()
    mkt = load_market()

    # 市场状态用"上月末"取值 -> 本月决策时已知(无前视)
    mkt_prev = mkt.copy()
    mkt_prev.index = mkt_prev.index + pd.offsets.MonthEnd(1)
    mkt_prev = mkt_prev[~mkt_prev.index.duplicated(keep="last")]
    panel["_mend"] = pd.to_datetime(panel["月份"] + "-01") + pd.offsets.MonthEnd(0)
    panel = panel.merge(mkt_prev[MKT_FEATS], left_on="_mend", right_index=True, how="left")

    print(f"面板规模: {len(panel)} 个股票-月, {panel['标的'].nunique()} 只标的, "
          f"{panel['月份'].nunique()} 个月\n")
    print("=" * 120)
    print("1. 月度全景(国际复材): 先手层到底有没有用")
    print("=" * 120)
    g = panel[panel["标的"] == "国际复材"].copy()
    g["先手有效"] = np.where(g["先手贡献%"] > 0.5, "有效", np.where(g["先手贡献%"] < -0.5, "有害", "中性"))
    show = g[["月份", "月收益_先手开%", "月收益_先手关%", "先手贡献%", "月收益_持有%",
              "信号次数", "mkt_ret20", "mkt_vol20", "mkt_above_ma20", "mkt_margin_chg20"]]
    print(show.round(2).to_string(index=False))

    print("\n" + "=" * 120)
    print("2. 全样本(9只 x 21月): 先手贡献的分布")
    print("=" * 120)
    d = panel["先手贡献%"]
    print(f"均值 {d.mean():+.2f}% | 中位 {d.median():+.2f}% | 为正的比例 {(d>0).mean()*100:.0f}% | "
          f"最好 {d.max():+.1f}% | 最差 {d.min():+.1f}%")
    print("\n按标的:")
    print(panel.groupby("标的")["先手贡献%"].agg(["mean", "median",
          lambda s: (s > 0).mean() * 100]).rename(columns={"<lambda_0>": "为正比例%"}).round(2).to_string())

    print("\n" + "=" * 120)
    print("3. 哪些市场状态能事前区分 先手有效 / 先手有害 ?")
    print("=" * 120)
    rows = []
    for f in MKT_FEATS:
        if f not in panel.columns:
            continue
        x = panel[f].astype(float)
        y = panel["先手贡献%"]
        ok = x.notna() & y.notna()
        if ok.sum() < 100:
            continue
        rho = x[ok].corr(y[ok], method="spearman")
        # 按该变量中位数分两组, 比较先手贡献
        med = x[ok].median()
        hi, lo = y[ok][x[ok] > med], y[ok][x[ok] <= med]
        rows.append({"市场变量": f, "Spearman": rho,
                     "高于中位时先手贡献%": hi.mean(), "低于中位时先手贡献%": lo.mean(),
                     "高组为正比例%": (hi > 0).mean() * 100, "低组为正比例%": (lo > 0).mean() * 100,
                     "差异": hi.mean() - lo.mean()})
    t = pd.DataFrame(rows).sort_values("差异")
    print(t.round(3).to_string(index=False))

    print("\n" + "=" * 120)
    print("4. 候选 gate 的效果: 只在市场状态满足时才允许先手层")
    print("=" * 120)
    gates = {
        "无gate(始终允许先手)": lambda p: pd.Series(True, index=p.index),
        "创业板指在MA20上方": lambda p: p["mkt_above_ma20"] == 1,
        "创业板指 MA20>MA60": lambda p: p["mkt_ma20_gt_ma60"] == 1,
        "创业板指20日波动 < 25%": lambda p: p["mkt_vol20"] < 25,
        "创业板指20日波动 < 30%": lambda p: p["mkt_vol20"] < 30,
        "创业板指20日涨幅 > -3%": lambda p: p["mkt_ret20"] > -3,
        "两融余额20日变化 > 0": lambda p: p["mkt_margin_chg20"] > 0,
        "波动<30% 且 指数在MA20上方": lambda p: (p["mkt_vol20"] < 30) & (p["mkt_above_ma20"] == 1),
        "波动<30% 且 MA20>MA60": lambda p: (p["mkt_vol20"] < 30) & (p["mkt_ma20_gt_ma60"] == 1),
    }
    rows = []
    for name, fn in gates.items():
        allow = fn(panel).fillna(False)
        eff = panel["先手贡献%"].where(allow, 0.0)      # 不允许先手的月份 -> 贡献记为 0
        rows.append({"gate": name, "允许比例%": allow.mean() * 100,
                     "先手贡献均值%": panel["先手贡献%"].mean(),
                     "gated后均值%": eff.mean(),
                     "被过滤掉的天数占比%": (1 - allow.mean()) * 100})
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    # 5) 落到组合层面: gate 开关对"先手层"的实际影响
    print("\n" + "=" * 120)
    print("5. 组合层面验证: 用 gate 过滤先手层后的回测(国际复材)")
    print("=" * 120)
    feat = sl.add_features(sl.load_panel()).replace([np.inf, -np.inf], np.nan)
    pos = stock_position(feat, True)
    pos_off = stock_position(feat, False)
    mkt_daily = mkt.reindex(feat.index).ffill()
    for name, cond in (("无gate", pd.Series(True, index=feat.index)),
                       ("指数在MA20上方才允许先手", (mkt_daily["mkt_above_ma20"] == 1)),
                       ("波动<30%才允许先手", (mkt_daily["mkt_vol20"] < 30)),
                       ("波动<30%且指数在MA20上方", (mkt_daily["mkt_vol20"] < 30)
                        & (mkt_daily["mkt_above_ma20"] == 1))):
        c = cond.reindex(feat.index).fillna(False).to_numpy()
        p = pos.to_numpy(float).copy()
        off = pos_off.to_numpy(float)
        # 先手日的仓位用"先手关"版的仓位替换
        is_dip = (p > 0) & (np.abs(p - 0.7) < 1e-6) & (off < 1e-6)
        p[is_dip & ~c] = 0.0
        s = pd.Series(p, index=feat.index)
        for lab, (a, b) in (("25-01~26-09", STUDY), ("2025", ("2025-01-01", "2025-12-31")),
                            ("2026", ("2026-01-01", "2026-09-11"))):
            m = sl.backtest(feat.loc[a:b], s.loc[a:b]).metrics
            print(f"  {name:24s} {lab:4s} 收益 {m['total_return_pct']:7.1f}% | 回撤 {m['max_drawdown_pct']:6.1f}% | "
                  f"Sharpe {m['sharpe']:.2f} | 信号 {m['n_trades']:2d} 笔")
        print()

    panel.to_csv("results_macro_panel.csv", index=False, encoding="utf-8-sig")
    t.to_csv("results_macro_separation.csv", index=False, encoding="utf-8-sig")
    print("-> results_macro_panel.csv / results_macro_separation.csv")


if __name__ == "__main__":
    main()
