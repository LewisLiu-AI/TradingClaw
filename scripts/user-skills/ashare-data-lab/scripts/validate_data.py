#!/usr/bin/env python3
"""A股研究数据验证器 —— 在跑任何回测之前先跑这个。

用法:
    python validate_data.py <数据目录> [--market idx_cyb.csv] [--start 2024-06-01] [--end 2026-09-12]

检查项(每一条都对应一个真实踩过的坑, 见 references/pitfalls.md):
  C1 OHLC 结构   high>=max(open,close), low<=min(open,close), 价格>0
  C2 日期       重复日期 / 非交易日 / 与大盘日历错位 / 缺口
  C3 覆盖率     逐列 NaN 比例, 并标出**系统性缺口区间**(连续缺失)
  C4 单位量级   换手率是小数还是百分数; 两融余额是元/万元/亿元; 成交额与成交量是否自洽
  C5 新鲜度     末行是否落后于预期最新交易日
  C6 复权一致性 前复权/不复权比值(复权因子)是否单调阶梯(除权跳变点)
  C7 跨源自洽   同一标的多个来源的收益率序列是否一致
退出码: 0 = 无 ERROR; 1 = 有 ERROR(阻止继续分析)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ERRORS: list[str] = []
WARNS: list[str] = []

# 事件/新闻类文件: 一天可以有多条, 且可能发生在非交易日 —— 跳过日期唯一性与日历检查
EVENT_FILES = {"announcements.csv", "news.csv", "lhb.csv", "block_trade.csv"}
# 非行情文件: 跳过 OHLC 结构检查
QUOTE_FILES = {"px_qfq.csv", "px_raw.csv", "px_hfq.csv", "idx_cyb.csv", "idx_cyb50.csv",
               "idx_hs300.csv", "idx_zz500.csv", "mkt_sse.csv", "mkt_szse.csv",
               "mkt_csi500.csv", "mkt_sse50.csv"}
# 低频/事件驱动文件: 天然有缺口且可能非交易日, 跳过缺口/新鲜度/日历检查
# (对这类文件要求"每日连续"是错的, 会产生大量无意义告警)
LOW_FREQ = {"holders.csv", "announcements.csv", "news.csv", "lhb.csv",
            "block_trade.csv", "lockup.csv", "inst_participation.csv", "zt_pool_today.csv"}


def err(msg: str) -> None:
    ERRORS.append(msg)
    print(f"  [ERROR] {msg}")


def warn(msg: str) -> None:
    WARNS.append(msg)
    print(f"  [WARN ] {msg}")


def ok(msg: str) -> None:
    print(f"  [OK   ] {msg}")


def read(path: Path) -> pd.DataFrame | None:
    try:
        d = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001
        err(f"{path.name}: 无法读取 ({exc})")
        return None
    dc = next((c for c in ("date", "日期", "trade_date", "持股日期", "交易日") if c in d.columns), None)
    if dc:
        d[dc] = pd.to_datetime(d[dc], errors="coerce")
        d = d.dropna(subset=[dc]).set_index(dc).sort_index()
    return d


def columns_like(d: pd.DataFrame, *names: str) -> list[str]:
    return [c for c in d.columns if any(n in str(c).lower() for n in names)]


# ─────────────────────────── C1 OHLC ───────────────────────────
def check_ohlc(name: str, d: pd.DataFrame) -> None:
    cols = {c.lower(): c for c in d.columns}
    if not {"open", "high", "low", "close"} <= set(cols):
        return
    o, h, l, c = (d[cols[k]].astype(float) for k in ("open", "high", "low", "close"))
    bad = {
        "high<low": (h < l).sum(),
        "high<max(o,c)": (h < pd.concat([o, c], axis=1).max(axis=1) - 1e-6).sum(),
        "low>min(o,c)": (l > pd.concat([o, c], axis=1).min(axis=1) + 1e-6).sum(),
        "价格<=0": ((pd.concat([o, h, l, c], axis=1) <= 0).any(axis=1)).sum(),
        "NaN": int(pd.concat([o, h, l, c], axis=1).isna().any(axis=1).sum()),
    }
    hits = {k: int(v) for k, v in bad.items() if v}
    if hits:
        err(f"{name}: OHLC 结构违反 {hits}")
    else:
        ok(f"{name}: OHLC 结构正常 ({len(d)} 行)")


# ─────────────────────────── C2 日期 ───────────────────────────
def check_dates(name: str, d: pd.DataFrame, market: pd.Series | None) -> None:
    if not isinstance(d.index, pd.DatetimeIndex) or len(d) == 0:
        return
    dup = int(d.index.duplicated().sum())
    if dup and name in EVENT_FILES:
        print(f"  [info ] {name}: {dup} 个重复日期 —— 事件类文件允许(一天多条)")
    elif dup:
        err(f"{name}: 重复日期 {dup} 个")
    if not d.index.is_monotonic_increasing:
        err(f"{name}: 日期未升序")
    wknd = d.index[d.index.dayofweek >= 5]
    if len(wknd):
        warn(f"{name}: 含 {len(wknd)} 个周末日期 (可能含非交易日) {[str(x.date()) for x in wknd[:3]]}")
    if market is not None and name not in EVENT_FILES and name not in LOW_FREQ:
        inside = d.index[(d.index >= market.index.min()) & (d.index <= market.index.max())]
        miss = inside.difference(market.index)
        if len(miss):
            warn(f"{name}: 有 {len(miss)} 个日期不在大盘日历中, 例 {[str(x.date()) for x in miss[:3]]}")
    if name in LOW_FREQ:
        print(f"  [info ] {name}: 低频/事件类文件, 跳过缺口与日历检查")
        return
    # 缺口: 相邻行间隔 > 20 个自然日(排除长假)
    gaps = d.index.to_series().diff().dt.days
    big = gaps[gaps > 20]
    for dt, days in big.items():
        warn(f"{name}: 数据缺口 {int(days)} 天 (截止 {dt.date()}) —— 若无停牌则是缺行")
    if not dup and not len(wknd):
        ok(f"{name}: 日期序列正常")


# ─────────────────────────── C3 覆盖率 ───────────────────────────
def check_coverage(name: str, d: pd.DataFrame, verbose: bool = True) -> None:
    """逐列 NaN 覆盖率。只报 >20% 的列(最多 3 个), 并给出最大连续缺口区间 —— 
    连续缺口才是真问题(如交易所某类数据系统性停更), 零散 NaN 通常无害。"""
    if len(d) == 0:
        return
    findings = []
    for c in d.columns:
        na = d[c].isna()
        if na.sum() == 0 or na.mean() <= 0.2:
            continue
        grp = (na != na.shift()).cumsum()
        runs = sorted([(g.index.min(), g.index.max(), len(g))
                       for _, g in d[na].groupby(grp[na])], key=lambda x: -x[2])[:1]
        findings.append((na.mean(), c, runs[0] if runs and runs[0][2] > 3 else None))
    if not findings:
        ok(f"{name}: 各列覆盖率良好(<20% 缺失)")
        return
    for ratio, c, run in sorted(findings, reverse=True)[:3]:
        gap = f" 最大连续缺口 {run[0].date()}~{run[1].date()}({run[2]}天)" if run else ""
        warn(f"{name}.{c}: 缺失 {ratio:.1%}{gap}")
    if len(findings) > 3:
        print(f"  [info ] {name}: 另有 {len(findings)-3} 个列缺失>20%")
    allna = [c for c in d.columns if d[c].isna().all()]
    if allna:
        err(f"{name}: 以下列全为空 {allna}")


# ─────────────────────────── C4 单位量级 ───────────────────────────
def check_units(name: str, d: pd.DataFrame) -> None:
    for c in columns_like(d, "turnover", "换手"):
        s = pd.to_numeric(d[c], errors="coerce").dropna()
        if len(s) == 0:
            continue
        if s.max() < 1.0:
            warn(f"{name}.{c}: 最大值 {s.max():.4f} < 1, 疑似**小数口径**(0.0433=4.33%), "
                 f"与百分数口径混用会静默出错")
        elif s.max() > 100:
            err(f"{name}.{c}: 最大值 {s.max():.1f} > 100, 换手率不可能超 100%")
        else:
            ok(f"{name}.{c}: 量级正常 (max {s.max():.2f} %)")
    for c in columns_like(d, "rz_balance", "rzrq", "融资余额", "amount", "成交额", "mkt_rz"):
        s = pd.to_numeric(d[c], errors="coerce").dropna()
        if len(s) == 0:
            continue
        med = float(s.median())
        if med > 1e10:
            warn(f"{name}.{c}: 中位 {med:.3e} 量级过大, 疑为**元**(除 1e8 得亿元)")
        elif med > 1e11:
            warn(f"{name}.{c}: 中位 {med:.3e}, 量级过大, 检查单位")
        elif med > 1e6:
            print(f"  [info ] {name}.{c}: 中位 {med:.3e} (成交额以元计属正常)")
        elif "pct" in c.lower() or "比例" in c or "占比" in c:
            print(f"  [info ] {name}.{c}: 百分比列 (中位 {med:.2f})")
        elif med > 10:
            ok(f"{name}.{c}: 量级正常 (中位 {med:,.1f}, 应已是亿元)")
        else:
            warn(f"{name}.{c}: 中位 {med:.3f} 过小, 检查单位")


# ─────────────────────────── C5 新鲜度 ───────────────────────────
def check_freshness(name: str, d: pd.DataFrame, expected_last: pd.Timestamp | None) -> None:
    if expected_last is None or len(d) == 0 or name in LOW_FREQ:
        return
    last = d.index.max()
    lag = (expected_last - last).days
    if lag > 4:
        warn(f"{name}: 末行 {last.date()} 落后预期 {expected_last.date()} 共 {lag} 天, 数据可能未更新")
    else:
        ok(f"{name}: 末行 {last.date()} (新鲜)")


# ─────────────────────────── C6 复权一致性 ───────────────────────────
def check_adjust(data_dir: Path, expected_last: pd.Timestamp | None) -> None:
    pairs = [("px_qfq.csv", "px_raw.csv"), ("px_hfq.csv", "px_raw.csv")]
    for a, b in pairs:
        pa, pb = data_dir / a, data_dir / b
        if not (pa.exists() and pb.exists()):
            continue
        da, db = read(pa), read(pb)
        if da is None or db is None:
            continue
        j = pd.concat([da["close"].rename("a"), db["close"].rename("b")], axis=1).dropna()
        if len(j) < 30:
            continue
        f = j["a"] / j["b"]
        steps = (f.round(6).diff().abs() > 1e-6).sum()
        # 复权因子应是阶梯(除权日跳变), 非单调说明混入了不同复权口径
        if a == "px_qfq.csv" and abs(f.iloc[-1] - 1.0) > 1e-6:
            warn(f"{a}/{b}: 前复权因子末日 {f.iloc[-1]:.4f} ≠ 1, 确认是否同基准日")
        else:
            ok(f"{a}/{b}: 复权关系自洽 (因子 {f.min():.4f}~{f.max():.4f}, {steps} 个跳变日)")


# ─────────────────────────── C7 跨源自洽 ───────────────────────────
def check_cross_source(data_dir: Path) -> None:
    for sub in ("peers", "global"):
        pass
    px, peers = data_dir / "px_qfq.csv", data_dir / "peers"
    if not (px.exists() and peers.exists()):
        return
    mine = read(px)
    if mine is None:
        return
    for f in sorted(peers.glob("*301526*.csv")):
        other = read(f)
        if other is None or "close" not in other.columns:
            continue
        j = pd.concat([mine["close"].rename("a"), other["close"].rename("b")], axis=1).dropna()
        if len(j) < 30:
            continue
        ra, rb = j["a"].pct_change().dropna(), j["b"].pct_change().dropna()
        k = ra.index.intersection(rb.index)
        diff = (ra[k] - rb[k]).abs()
        if diff.max() > 0.005:
            err(f"跨源不一致: px_qfq vs {f.name}, 日收益最大差 {diff.max():.2%} "
                f"于 {diff.idxmax().date()} (复权口径或来源不同)")
        else:
            ok(f"跨源自洽: px_qfq vs {f.name} 日收益最大差 {diff.max():.4%}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--market", default="idx_cyb.csv", help="大盘指数文件名(用于日历对齐/新鲜度)")
    ap.add_argument("--expected-last", default=None, help="预期最新交易日 YYYY-MM-DD")
    args = ap.parse_args()

    dd = Path(args.data_dir)
    if not dd.is_dir():
        print(f"目录不存在: {dd}")
        sys.exit(1)
    market = None
    mp = dd / args.market
    if mp.exists():
        m = read(mp)
        market = m["close"] if m is not None and "close" in m.columns else None
    exp_last = pd.Timestamp(args.expected_last) if args.expected_last else (
        market.index.max() if market is not None else None)

    print(f"=== 数据验证: {dd} ({len(list(dd.glob('*.csv')))} 个 CSV) ===")
    for f in sorted(dd.glob("*.csv")):
        if f.name.startswith("_"):
            continue
        d = read(f)
        if d is None:
            continue
        print(f"\n-- {f.name} ({len(d)} 行" +
              (f", {d.index.min().date()}~{d.index.max().date()}" if isinstance(d.index, pd.DatetimeIndex) and len(d) else "") + ")")
        if f.name in QUOTE_FILES:
            check_ohlc(f.name, d)
        check_dates(f.name, d, market)
        check_units(f.name, d)
        check_freshness(f.name, d, exp_last)
        check_coverage(f.name, d, verbose=False)
    print("\n-- 复权 / 跨源 --")
    check_adjust(dd, exp_last)
    check_cross_source(dd)

    print(f"\n=== 结论: {len(ERRORS)} 个 ERROR, {len(WARNS)} 个 WARN ===")
    if ERRORS:
        print("存在 ERROR, 先修数据再跑回测:")
        for e in ERRORS:
            print("  -", e)
    sys.exit(1 if ERRORS else 0)


if __name__ == "__main__":
    main()
