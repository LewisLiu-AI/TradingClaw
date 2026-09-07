#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""科创50 利空预警模型 v1.1 —— 每日打分器（报告 §7.4 每日运行流程的自动化实现）。

自动计算（仅依赖本目录数据）:
    E1  拥挤过热: 20日涨幅>10% 且 量比>1.2 → +3；20日涨幅>15% → +2（两者取高）
    A1  隔夜SOXX: ≤-2% → +2；(-2%,-1%] → +1
    A2  隔夜QQQ : ≤-2% → +1（与 A1 不叠加取高）
    D3  汇率急贬: USDCNH 10日涨幅>1.5% → +1.5
事件类因子（需人工判断，命中则传开关）:
    A3 海外事件窗口+1 | A1a 亚洲同链共振+1 | B1 中美摩擦+3 | B2 地缘冲突+2
    C1 会议/数据落地+1.5 | C2 权重股财报窗口+1 | D1 杠杆恶化(+2/+2) | D2 外资流出+1.5
    E1a 成交集中度+1.5 | E2 减持公告+2 | E3 巨量解禁+1 | E4 巨量IPO+1.5
乘数 M: PE(5年分位)>85% → 总分×1.25（封顶15）
级别: Ⅰ绿 0-2 常态 | Ⅱ黄 3-5 单因子 | Ⅲ橙 6-8 双因子共振 | Ⅳ红 ≥9 事件+脆弱共振

用法:
    python3 daily_score.py                         # 用 star50_index.csv 最新日；隔夜读 data/soxx.csv、data/qqq.csv（若有）
    python3 daily_score.py --soxx -1.2 --qqq -0.5  # 隔夜涨跌幅手工传入（%）
    python3 daily_score.py --date 2024-10-08       # 历史复演（E1 按该日滚动值）
    python3 daily_score.py --b1 --c1 --fx10d 0.2   # 事件因子命中开关 / 汇率10日涨幅
    python3 daily_score.py --pe-percentile 90      # 启用 M 乘数
"""
import argparse
import csv
import os

BASE = os.path.dirname(os.path.abspath(__file__))


def load_index():
    dates, closes, vols = [], [], []
    with open(os.path.join(BASE, "star50_index.csv")) as f:
        for row in csv.DictReader(f):
            dates.append(row["date"])
            closes.append(float(row["close"]))
            vols.append(float(row["volume"]))
    return dates, closes, vols


def latest_us_pct(name):
    path = os.path.join(BASE, "data", f"{name}.csv")
    if not os.path.exists(path):
        return None
    closes = []
    with open(path) as f:
        for row in csv.DictReader(f):
            try:
                closes.append((row["date"], float(row["close"])))
            except (KeyError, ValueError):
                continue
    if len(closes) < 2:
        return None
    (d0, c0), (d1, c1) = closes[-2], closes[-1]
    return {"date": d1, "pct": (c1 / c0 - 1) * 100}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="评估基准日（默认用指数CSV最新交易日）")
    ap.add_argument("--soxx", type=float, help="隔夜SOXX涨跌幅%%（缺省读 data/soxx.csv）")
    ap.add_argument("--qqq", type=float, help="隔夜QQQ涨跌幅%%")
    ap.add_argument("--fx10d", type=float, help="USDCNH 10日涨幅%%")
    ap.add_argument("--pe-percentile", type=float, help="科创50 PE 5年分位（%%），>85 启用M乘数")
    for flag in ["a3", "a1a", "b1", "b2", "c1", "c2", "d1-lever", "d1-crash", "d2", "e1a", "e2", "e3", "e4"]:
        ap.add_argument(f"--{flag}", action="store_true", help="事件因子命中开关")
    args = ap.parse_args()

    dates, closes, vols = load_index()
    n = len(dates)
    t = n - 1 if not args.date else dates.index(args.date)
    date = dates[t]

    mom20 = (closes[t] / closes[t - 20] - 1) * 100 if t >= 20 else None
    vr20 = vols[t] / (sum(vols[t - 19:t + 1]) / 20.0) if t >= 20 else None

    rows = []
    total = 0.0

    # ---- E1 拥挤过热（自动）----
    e1 = 0.0
    why = []
    if mom20 is not None:
        if mom20 > 10 and vr20 > 1.2:
            e1 = max(e1, 3.0)
            why.append(f"20日涨幅{mom20:.1f}%>10 且 量比{vr20:.2f}>1.2")
        if mom20 > 15:
            e1 = max(e1, 2.0)
            why.append(f"20日涨幅{mom20:.1f}%>15")
    total += e1
    rows.append(("E1 拥挤过热", e1, "；".join(why) if why else f"20日涨幅 {mom20 and round(mom20,1)}%，量比 {vr20 and round(vr20,2)} —— 无触发"))

    # ---- A1/A2 隔夜（自动/半自动）----
    soxx = args.soxx if args.soxx is not None else (latest_us_pct("soxx") or {}).get("pct")
    qqq = args.qqq if args.qqq is not None else (latest_us_pct("qqq") or {}).get("pct")
    a1 = 2.0 if (soxx is not None and soxx <= -2) else (1.0 if (soxx is not None and soxx <= -1) else 0.0)
    a2 = 1.0 if (qqq is not None and qqq <= -2) else 0.0
    a_score = max(a1, a2)  # 与A1不叠加取高
    total += a_score
    rows.append(("A1/A2 隔夜SOXX/QQQ（取高）", a_score, f"SOXX {'—' if soxx is None else f'{soxx:.2f}%'} → {a1:+.0f}；QQQ {'—' if qqq is None else f'{qqq:.2f}%'} → {a2:+.0f}"))

    # ---- D3 汇率（半自动）----
    d3 = 1.5 if (args.fx10d is not None and args.fx10d > 1.5) else 0.0
    total += d3
    rows.append(("D3 汇率急贬", d3, f"USDCNH 10日 {args.fx10d if args.fx10d is None else args.fx10d}%（阈值>1.5%）"))

    # ---- 事件类人工开关 ----
    manual = [
        (args.a3, "A3 海外事件窗口", 1.0), (args.a1a, "A1a 亚洲同链共振", 1.0),
        (args.b1, "B1 中美摩擦升级", 3.0), (args.b2, "B2 地缘军事冲突", 2.0),
        (args.c1, "C1 会议/数据落地", 1.5), (args.c2, "C2 权重股财报窗口", 1.0),
        (args.d1_lever, "D1 杠杆资金恶化(降幅)", 2.0), (args.d1_crash, "D1 敲入风险区", 2.0),
        (args.d2, "D2 外资流出代理", 1.5), (args.e1a, "E1a 成交集中度>40%", 1.5),
        (args.e2, "E2 减持公告", 2.0), (args.e3, "E3 巨量解禁", 1.0), (args.e4, "E4 巨量IPO抽血", 1.5),
    ]
    for hit, name, pts in manual:
        if hit:
            total += pts
            rows.append((name, pts, "人工确认命中"))

    # ---- M 乘数 ----
    multiplier = 1.0
    if args.pe_percentile is not None and args.pe_percentile > 85:
        multiplier = 1.25
    final = min(total * multiplier, 15.0)

    if final >= 9:
        lv, name, act = "Ⅳ", "红色", "仓位≤20%或完全对冲；等待触发证伪+拥挤度回落后再评估；禁止抄底"
        color = "\033[41;97m"
    elif final >= 6:
        lv, name, act = "Ⅲ", "橙色", "仓位≤50%；停止逢跌加仓；期指/期权对冲β；逐日复盘触发链"
        color = "\033[43;30m"
    elif final >= 3:
        lv, name, act = "Ⅱ", "黄色", "仓位≤80%；暂停加仓计划；当日盘面复核触发因子"
        color = "\033[33m"
    else:
        lv, name, act = "Ⅰ", "绿色", "常态运行；绿色≠抄底信号"
        color = "\033[32m"

    print(f"评估基准日: {date}（指数收盘 {closes[t]:.2f}）")
    print("-" * 72)
    for name_, pts, note in rows:
        if pts or name_.startswith(("E1", "A1", "D3")):
            print(f"  {name_:<26s} {pts:>4}   {note}")
    if multiplier > 1:
        print(f"  {'M 乘数（PE分位>85%）':<24s} x1.25  总分放大并封顶15")
    print("-" * 72)
    print(f"总分 {total:g}" + (f" ×1.25 = {final:g}" if multiplier > 1 else f" → {final:g}") + f"  ⇒  {color}级别 {lv} {name}\033[0m")
    print(f"操作纪律: {act}")
    print("提示: B/C/D1/D2/E 类事件因子依赖人工/新闻扫描确认，未命中≠不存在。")


if __name__ == "__main__":
    main()
