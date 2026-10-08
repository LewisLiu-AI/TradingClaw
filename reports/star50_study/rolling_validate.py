#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阈值稳定性 / 分时段样本外检验（v2.0 预研）。

模型 v1.0 的校准统计是全样本一次性计算（存在后视镜偏差质疑）。本脚本检验：
量化因子（E1 拥挤过热、急涨、趋势、连跌、平静）全部只依赖当日及以前的数据，
把样本切成"拟合期 / 检验期"两段，观察条件概率的提升倍数是否在样本外保持。

用法:
    python3 rolling_validate.py            # 打印两段对比
    python3 rolling_validate.py --write    # 结果写入 artifacts/rolling_calibration.json

口径与 build_artifacts.py 完全一致：
    大跌日 = 单日涨跌幅 ≤ -1.5%；next5 = 此后 5 个交易日内出现大跌日
    mom_20d / vol_ratio_20(含当日20日均量) / MA60 均为滚动当日值，无未来函数
"""
import json
import os
import statistics

BASE = os.path.dirname(os.path.abspath(__file__))
IDX = os.path.join(BASE, "star50_index.csv")
ART = os.path.join(BASE, "artifacts")
DROP_TH = -1.5
SPLIT = "2024-01-01"  # 拟合期: < SPLIT；检验期: >= SPLIT


def main():
    dates, closes, vols = [], [], []
    with open(IDX) as f:
        import csv
        for row in csv.DictReader(f):
            dates.append(row["date"])
            closes.append(float(row["close"]))
            vols.append(float(row["volume"]))
    n = len(dates)

    pct = [None] * n
    mom = [None] * n
    vr = [None] * n
    ma60 = [None] * n
    for i in range(1, n):
        pct[i] = (closes[i] / closes[i - 1] - 1) * 100
    for i in range(20, n):
        mom[i] = (closes[i] / closes[i - 20] - 1) * 100
        vr[i] = vols[i] / (sum(vols[i - 19:i + 1]) / 20.0)
    for i in range(59, n):
        ma60[i] = sum(closes[i - 59:i + 1]) / 60.0

    def next5(i):
        return any(pct[j] is not None and pct[j] <= DROP_TH for j in range(i + 1, min(i + 6, n)))

    label = [next5(i) for i in range(n)]

    conds = {
        "base_all": lambda i: True,
        "e1_hot(mom20>10,vr>1.2)": lambda i: mom[i] is not None and mom[i] > 10 and vr[i] is not None and vr[i] > 1.2,
        "e1_surge(mom20>15)": lambda i: mom[i] is not None and mom[i] > 15,
        "trend_below_ma60": lambda i: ma60[i] is not None and closes[i] < ma60[i],
        "two_down_closes": lambda i: i >= 2 and closes[i - 1] < closes[i - 2] and closes[i] < closes[i - 1],
        "calm(|mom20|<=5,vr<1.1)": lambda i: mom[i] is not None and abs(mom[i]) <= 5 and vr[i] is not None and vr[i] < 1.1,
    }
    windows = [("拟合期 2020-07~2023-12", lambda d: d < SPLIT), ("检验期 2024-01~2026-09", lambda d: d >= SPLIT)]

    result = {"split": SPLIT, "generated": __import__("datetime").date.today().isoformat(), "windows": {}}
    print(f"{'条件':<28}", end="")
    for name, _ in windows:
        print(f"| {name[:14]:<16} P%     n    ", end="")
    print()
    for cname, fn in conds.items():
        print(f"{cname:<28}", end="")
        row = {}
        for wname, wfn in windows:
            sel = [label[i] for i in range(n) if wfn(dates[i]) and fn(i)]
            p = round(100 * sum(sel) / len(sel), 1) if sel else None
            row[wname] = {"pct": p, "n": len(sel)}
            print(f"| {str(p):>8} {len(sel):>6}   ", end="")
        result["windows"][cname] = row
        print()

    # 提升倍数（条件概率 / 该段基准）
    base = {w: result["windows"]["base_all"][w]["pct"] for w, _ in windows}
    print(f"{'提升倍数(条件/基准)':<26}", end="")
    for cname in conds:
        if cname == "base_all":
            continue
        lifts = []
        for w, _ in windows:
            d = result["windows"][cname][w]
            lifts.append(round(d["pct"] / base[w], 2) if d["pct"] is not None else None)
        result["windows"][cname]["lift"] = dict(zip([w for w, _ in windows], lifts))
        print(f"| fit x{lifts[0]:<7} oos x{lifts[1]:<6}", end="")
    print()

    # 各段大跌日基数
    for wname, wfn in windows:
        dn = sum(1 for i in range(n) if wfn(dates[i]) and pct[i] is not None and pct[i] <= DROP_TH)
        print(f"{wname}: 大跌日 {dn} 个")

    if "--write" in __import__("sys").argv:
        out = os.path.join(ART, "rolling_calibration.json")
        with open(out, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        print("written:", out)


if __name__ == "__main__":
    main()
