#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 star50_index.csv 重算 artifacts/（drop_days.csv / episodes.csv / summary.json）。

用法:
    python3 build_artifacts.py            # 干跑：重算并与现有 artifacts 比对，打印差异，不写盘
    python3 build_artifacts.py --write    # 覆盖写 artifacts/（建议先干跑确认差异符合预期）

规则（与 2026-09 全样本报告口径一致）:
    大跌日   = 单日涨跌幅 ≤ -1.5%
    事件簇   = 间隔 ≤5 个交易日的大跌日归并；episode_id 全局递增
    隔夜美股 = drop_days.csv 的 overnight_qqq/overnight_soxx 列：来自 data/qqq.csv、data/soxx.csv
               （date,close，美股日K，Yahoo chart API）按"A 股交易日 t 之前最近一个美股收盘日
               的涨跌幅"计算；data/ 缺失的日期沿用旧值。summary.json 的
               model_calibration.overnight_us_conditions 同理自动计算（data/ 覆盖全历史时）。
"""
import csv
import json
import os
import statistics
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
IDX = os.path.join(BASE, "star50_index.csv")
ART = os.path.join(BASE, "artifacts")
DATA = os.path.join(BASE, "data")
WRITE = "--write" in sys.argv

DROP_TH = -1.5
GAP = 5


def load_index():
    dates, closes, vols = [], [], []
    with open(IDX) as f:
        for row in csv.DictReader(f):
            dates.append(row["date"])
            closes.append(float(row["close"]))
            vols.append(float(row["volume"]))
    return dates, closes, vols


def load_us(name):
    """返回 [(date, pct_chg)] 按日期升序；无文件返回 None。"""
    path = os.path.join(DATA, f"{name}.csv")
    if not os.path.exists(path):
        return None
    out = []
    with open(path) as f:
        rows = list(csv.DictReader(f))
    prev = None
    for r in rows:
        try:
            c = float(r["close"])
        except (KeyError, ValueError):
            continue
        if prev is not None:
            out.append((r["date"], (c / prev - 1) * 100))
        prev = c
    return out


def overnight_for(dates, us_series):
    """对每个 A 股日期 t，取日期严格早于 t 的最近一条美股涨跌幅。"""
    if not us_series:
        return {}
    out, j = {}, -1
    for t in dates:
        while j + 1 < len(us_series) and us_series[j + 1][0] < t:
            j += 1
        if j >= 0:
            out[t] = round(us_series[j][1], 2)
    return out


def main():
    dates, closes, vols = load_index()
    n = len(dates)

    pct = [None] * n
    mom20 = [None] * n
    vr20 = [None] * n
    ma60 = [None] * n
    for i in range(1, n):
        pct[i] = (closes[i] / closes[i - 1] - 1) * 100
    for i in range(20, n):
        mom20[i] = (closes[i] / closes[i - 20] - 1) * 100
        vr20[i] = vols[i] / (sum(vols[i - 19:i + 1]) / 20.0)
    for i in range(59, n):
        ma60[i] = sum(closes[i - 59:i + 1]) / 60.0

    def fwd(i, k):
        return (closes[i + k] / closes[i] - 1) * 100 if i + k < n else None

    old_drop = {}
    old_path = os.path.join(ART, "drop_days.csv")
    if os.path.exists(old_path):
        with open(old_path) as f:
            for r in csv.DictReader(f):
                old_drop[r["date"]] = r

    qqq = overnight_for(dates, load_us("qqq"))
    soxx = overnight_for(dates, load_us("soxx"))

    def onight(t, mapping, col):
        if t in mapping:
            return f"{mapping[t]:.2f}"
        if t in old_drop and old_drop[t].get(col):
            return old_drop[t][col]
        return ""

    drop_rows = []
    for i in range(1, n):
        if pct[i] is not None and pct[i] <= DROP_TH:
            below = ""
            if ma60[i] is not None:
                below = "1" if closes[i] < ma60[i] else "0"
            drop_rows.append({
                "date": dates[i],
                "close": f"{closes[i]:.2f}",
                "pct_chg": f"{pct[i]:.2f}",
                "mom_20d": "" if mom20[i] is None else f"{mom20[i]:.2f}",
                "vol_ratio_20": "" if vr20[i] is None else f"{vr20[i]:.2f}",
                "overnight_qqq": onight(dates[i], qqq, "overnight_qqq"),
                "overnight_soxx": onight(dates[i], soxx, "overnight_soxx"),
                "fwd_1d": "" if fwd(i, 1) is None else f"{fwd(i, 1):.2f}",
                "fwd_5d": "" if fwd(i, 5) is None else f"{fwd(i, 5):.2f}",
                "fwd_20d": "" if fwd(i, 20) is None else f"{fwd(i, 20):.2f}",
                "below_ma60": below,
            })

    # ---- episodes ----
    idxs = [dates.index(r["date"]) for r in drop_rows]
    episodes, cur = [], [idxs[0]]
    for i in idxs[1:]:
        if i - cur[-1] <= GAP:  # 相邻大跌日索引差≤5（与既有91簇口径一致）
            cur.append(i)
        else:
            episodes.append(cur)
            cur = [i]
    episodes.append(cur)

    ep_rows = []
    for eid, idx_list in enumerate(episodes, start=1):
        drops = [pct[i] for i in idx_list]
        cum = 100 * (closes[idx_list[-1]] / closes[dates.index(dates[idx_list[0]]) - 1] if dates.index(dates[idx_list[0]]) > 0 else closes[idx_list[-1]] / closes[idx_list[0]]) - 100
        base = closes[idx_list[0] - 1] if idx_list[0] > 0 else closes[idx_list[0]]
        cum = (closes[idx_list[-1]] / base - 1) * 100
        ep_rows.append({
            "episode_id": eid,
            "dates": str([dates[i] for i in idx_list]),
            "drops": str([round(d, 2) for d in drops]),
            "n_days": len(idx_list),
            "cum_drop_pct": f"{cum:.2f}",
            "start": dates[idx_list[0]],
            "end": dates[idx_list[-1]],
        })

    # ---- summary ----
    def next5_bigdrop(i):
        return any(pct[j] is not None and pct[j] <= DROP_TH for j in range(i + 1, min(i + 6, n)))

    all_flags = [next5_bigdrop(i) for i in range(n)]

    def cond_pct(mask):
        sel = [all_flags[i] for i in range(n) if mask(i)]
        if not sel:
            return None, 0
        return 100.0 * sum(sel) / len(sel), len(sel)

    calib = {}
    calib["p_next5_bigdrop_all_days"] = dict(zip(("pct", "n"), cond_pct(lambda i: True)))
    calib["p_next5_bigdrop_below_ma60"] = dict(zip(("pct", "n"), cond_pct(lambda i: ma60[i] is not None and closes[i] < ma60[i])))
    calib["p_next5_bigdrop_hot_mom20gt10_volratio12"] = dict(zip(("pct", "n"), cond_pct(lambda i: mom20[i] is not None and mom20[i] > 10 and vr20[i] is not None and vr20[i] > 1.2)))
    calib["p_next5_bigdrop_mom20gt15"] = dict(zip(("pct", "n"), cond_pct(lambda i: mom20[i] is not None and mom20[i] > 15)))
    calib["p_next5_bigdrop_two_down_days"] = dict(zip(("pct", "n"), cond_pct(lambda i: i >= 2 and closes[i - 1] < closes[i - 2] and closes[i] < closes[i - 1])))
    calib["p_next5_bigdrop_calm_regime"] = dict(zip(("pct", "n"), cond_pct(lambda i: mom20[i] is not None and abs(mom20[i]) <= 5 and vr20[i] is not None and vr20[i] < 1.1)))
    for v in calib.values():
        v["pct"] = round(v["pct"], 1) if v["pct"] is not None else None

    # ---- 隔夜美股条件概率（全样本，需 data/qqq.csv、data/soxx.csv）----
    overnight_us = None
    if qqq and soxx:
        def cond_us(mapping, thr):
            days = [(mapping.get(dates[i]), pct[i]) for i in range(1, n)]
            days = [(o, p) for o, p in days if o is not None and o <= -thr]
            if not days:
                return None, 0
            hit = sum(1 for o, p in days if p is not None and p <= DROP_TH)
            return round(100.0 * hit / len(days), 1), len(days)
        overnight_us = {}
        for name, mapping in (("qqq", qqq), ("soxx", soxx)):
            for thr in (1.0, 1.5, 2.0):
                p, n_ = cond_us(mapping, thr)
                overnight_us[f"overnight_{name}_le_{thr}pct"] = {
                    "p_star50_drop_same_day_pct": p, "n": n_}
    calib["overnight_us_conditions"] = overnight_us  # None => 沿用旧值

    by_year = {}
    for r in drop_rows:
        y = r["date"][:4]
        by_year.setdefault(y, []).append(float(r["pct_chg"]))
    by_year = {y: {"count": len(v), "avg_drop_pct": round(sum(v) / len(v), 2), "worst_drop_pct": min(v)} for y, v in sorted(by_year.items())}

    def bucket(p):
        if p <= -4:
            return "<-4"
        if p <= -3:
            return "-3~-4"
        if p <= -2:
            return "-2~-3"
        return "-1.5~-2"

    bucket_dist = {"-1.5~-2": 0, "-2~-3": 0, "-3~-4": 0, "<-4": 0}
    for r in drop_rows:
        bucket_dist[bucket(float(r["pct_chg"]))] += 1

    med = lambda v: statistics.median(v)
    f1 = [float(r["fwd_1d"]) for r in drop_rows if r["fwd_1d"]]
    f5 = [float(r["fwd_5d"]) for r in drop_rows if r["fwd_5d"]]
    f20 = [float(r["fwd_20d"]) for r in drop_rows if r["fwd_20d"]]
    f5_all = [fwd(i, 5) for i in range(n) if fwd(i, 5) is not None]
    fwd_after = {
        "fwd_1d_median": round(med(f1), 2), "fwd_5d_median": round(med(f5), 2),
        "fwd_20d_median": round(med(f20), 2),
        "fwd_5d_median_baseline_all_days": round(med(f5_all), 2),
    }

    qvals = [float(r["overnight_qqq"]) for r in drop_rows if r["overnight_qqq"]]
    svals = [float(r["overnight_soxx"]) for r in drop_rows if r["overnight_soxx"]]
    overnight_drop = {
        "qqq_median": round(med(qvals), 2), "qqq_le_minus1_share": round(100 * sum(1 for v in qvals if v <= -1) / len(qvals), 1),
        "soxx_median": round(med(svals), 2), "soxx_le_minus2_share": round(100 * sum(1 for v in svals if v <= -2) / len(svals), 1),
    }

    new_summary = {
        "star_code": "000688.SH",
        "window": {"start": dates[0], "end": dates[-1], "n_days": n},
        "drop_days": {"count": len(drop_rows), "share_pct": round(100 * len(drop_rows) / n, 2)},
        "by_year": by_year,
        "bucket_dist": bucket_dist,
        "episodes": {"count": len(ep_rows), "multi_day": sum(1 for e in ep_rows if int(e["n_days"]) > 1)},
        "fwd_after_drop_days": fwd_after,
        "overnight_us_on_drop_days": overnight_drop,
        "model_calibration": calib,
    }

    # ---- 与现有 artifacts 比对 ----
    old_summary_path = os.path.join(ART, "summary.json")
    if os.path.exists(old_summary_path):
        old_summary = json.load(open(old_summary_path))
        for k, v in new_summary.items():
            if k == "model_calibration":
                old = old_summary.get(k, {})
                for kk, vv in v.items():
                    if kk == "overnight_us_conditions":
                        if vv is None:
                            print(f"[KEEP] calib.overnight_us_conditions: data/ 缺失，沿用旧值")
                        else:
                            for k3, v3 in vv.items():
                                o = old.get("overnight_us_conditions", {}).get(k3, {})
                                flag = "OK " if abs((o.get("p_star50_drop_same_day_pct") or 0) - (v3["p_star50_drop_same_day_pct"] or 0)) < 0.15 and o.get("n") == v3["n"] else "DIFF"
                                print(f"[{flag}] calib.overnight_us.{k3}: new=({v3['p_star50_drop_same_day_pct']},n={v3['n']}) old=({o.get('p_star50_drop_same_day_pct')},n={o.get('n')})")
                        continue
                    o = old.get(kk, {})
                    flag = "OK " if abs((o.get("pct") or 0) - (vv["pct"] or 0)) < 0.15 and o.get("n") == vv["n"] else "DIFF"
                    print(f"[{flag}] calib.{kk}: new=({vv['pct']},n={vv['n']}) old=({o.get('pct')},n={o.get('n')})")
            else:
                flag = "OK " if json.dumps(old_summary.get(k), sort_keys=True) == json.dumps(v, sort_keys=True) else "DIFF"
                print(f"[{flag}] summary.{k}")
                if flag == "DIFF":
                    print("   new:", json.dumps(v, ensure_ascii=False)[:300])
                    print("   old:", json.dumps(old_summary.get(k), ensure_ascii=False)[:300])

    # 与现有 episodes 比对簇数与最后几簇
    old_ep_path = os.path.join(ART, "episodes.csv")
    if os.path.exists(old_ep_path):
        with open(old_ep_path) as f:
            old_eps = list(csv.DictReader(f))
        same_n = len(old_eps) == len(ep_rows)
        print(f"[{'OK ' if same_n else 'DIFF'}] episodes count: new={len(ep_rows)} old={len(old_eps)}")
        if not same_n:
            for a, b in zip(ep_rows, old_eps):
                if a["start"] != b["start"] or a["end"] != b["end"]:
                    print("   first diverging episode:", a["episode_id"], a["start"], a["end"], "vs old", b["episode_id"], b["start"], b["end"])
                    break
            if len(ep_rows) > len(old_eps):
                print("   NEW episodes:")
                for e in ep_rows[len(old_eps):]:
                    print("   ", e["episode_id"], e["start"], "~", e["end"], e["cum_drop_pct"] + "%")

    new_drop_days = [r["date"] for r in drop_rows if r["date"] not in old_drop] if old_drop else []
    print(f"drop_days: total={len(drop_rows)}, 相对现有新增={new_drop_days or '无'}")

    if WRITE:
        os.makedirs(ART, exist_ok=True)
        with open(old_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(drop_rows[0].keys()))
            w.writeheader()
            w.writerows(drop_rows)
        with open(os.path.join(ART, "episodes.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(ep_rows[0].keys()))
            w.writeheader()
            w.writerows(ep_rows)
        if os.path.exists(old_summary_path):
            old_summary = json.load(open(old_summary_path))
            if new_summary["model_calibration"]["overnight_us_conditions"] is None:
                new_summary["model_calibration"]["overnight_us_conditions"] = old_summary["model_calibration"]["overnight_us_conditions"]
        with open(os.path.join(ART, "summary.json"), "w") as f:
            json.dump(new_summary, f, ensure_ascii=False, indent=1)
        print("written:", ART)
    else:
        print("dry-run（加 --write 落盘）")


if __name__ == "__main__":
    main()
