import json
import os
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd



def _load_config():
    for path in ("config.json", "../config.json", "../../config.json"):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            continue
    return {}


def _pick_star_code(data_map, config):
    for c in (config.get("codes") or []):
        if str(c).upper().endswith(".SH"):
            return str(c).upper()
    for c in data_map:
        if str(c).upper().endswith(".SH"):
            return str(c).upper()
    return list(data_map.keys())[0]


def _run_dir():
    import sys
    for a in sys.argv[1:]:
        p = Path(a)
        if p.is_dir() and (p / "config.json").exists():
            return p
    cands = sorted(Path.cwd().glob("runs/*/config.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if cands:
        return cands[0].parent
    return Path.cwd()


def _read_star_csv():
    rd = _run_dir()
    for path in (rd / "data" / "star50.csv", Path("data/star50.csv"), Path("star50.csv")):
        try:
            s = pd.read_csv(path, parse_dates=["date"]).set_index("date")
            s = s[~s.index.duplicated(keep="last")].sort_index()
            return s
        except Exception:
            continue
    return None


def _read_us_csv(name):
    rd = _run_dir()
    for path in (rd / "data" / ("%s.csv" % name), Path("data/%s.csv" % name), Path("%s.csv" % name)):
        try:
            s = pd.read_csv(path, parse_dates=["date"]).set_index("date")["close"].astype(float)
            s = s[~s.index.duplicated(keep="last")].sort_index()
            return s
        except Exception:
            continue
    return None


def _artifact_dir():
    p = os.path.join(os.getcwd(), "artifacts")
    try:
        os.makedirs(p, exist_ok=True)
        return p
    except Exception:
        return "."


class SignalEngine:
    """Event-study engine: STAR50 single-day drops <= -1.5%, with overnight US
    mapping (QQQ / SOXX), crowding stats, forward returns and conditional hit
    rates. Trading signal itself is a simple de-risk rule to satisfy the
    harness (flat the day after a big drop); the research output lives in
    artifacts/."""

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        config = _load_config()
        star = _pick_star_code(data_map, config)
        out_dir = _artifact_dir()

        df = data_map[star].copy()
        df.index = pd.to_datetime(df.index)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        _star_csv = _read_star_csv()
        if _star_csv is not None and len(_star_csv) > len(df):
            df = _star_csv
        close = df["close"].astype(float)
        ret = close.pct_change()

        us_close = {}
        for code, d in data_map.items():
            if str(code).upper().endswith(".US"):
                dd = d.copy()
                dd.index = pd.to_datetime(dd.index)
                dd = dd[~dd.index.duplicated(keep="last")].sort_index()
                us_close[str(code).split(".")[0].lower()] = dd["close"].astype(float)
        for name in ("qqq", "soxx"):
            if name not in us_close:
                s = _read_us_csv(name)
                if s is not None:
                    us_close[name] = s

        f1 = close.shift(-1) / close - 1
        f5 = close.shift(-5) / close - 1
        f20 = close.shift(-20) / close - 1
        mom20 = close / close.shift(20) - 1
        vol = df["volume"].astype(float)
        vol_ratio = vol / vol.rolling(20).mean()
        ma60 = close.rolling(60).mean()

        def overnight(us_name, t):
            if us_name not in us_close:
                return np.nan
            s = us_close[us_name]
            prior = s.index[s.index < t]
            if len(prior) == 0:
                return np.nan
            return float(s.loc[prior[-1]] / s.loc[prior[-2]] - 1) if len(prior) >= 2 else np.nan

        drop_idx = ret.index[ret <= -0.015]
        rows = []
        for t in drop_idx:
            i = df.index.get_loc(t)
            row = {
                "date": t.strftime("%Y-%m-%d"),
                "close": round(float(close.loc[t]), 2),
                "pct_chg": round(float(ret.loc[t]) * 100, 2),
                "mom_20d": round(float(mom20.loc[t]) * 100, 2) if pd.notna(mom20.loc[t]) else None,
                "vol_ratio_20": round(float(vol_ratio.loc[t]), 2) if pd.notna(vol_ratio.loc[t]) else None,
                "overnight_qqq": round(overnight("qqq", t) * 100, 2) if pd.notna(overnight("qqq", t)) else None,
                "overnight_soxx": round(overnight("soxx", t) * 100, 2) if pd.notna(overnight("soxx", t)) else None,
                "fwd_1d": round(float(f1.loc[t]) * 100, 2) if pd.notna(f1.loc[t]) else None,
                "fwd_5d": round(float(f5.loc[t]) * 100, 2) if pd.notna(f5.loc[t]) else None,
                "fwd_20d": round(float(f20.loc[t]) * 100, 2) if pd.notna(f20.loc[t]) else None,
                "below_ma60": bool(close.loc[t] < ma60.loc[t]) if pd.notna(ma60.loc[t]) else None,
            }
            rows.append(row)

        dd_df = pd.DataFrame(rows)

        # episodes: drop days within 5 trading days of each other
        trading_positions = {d: i for i, d in enumerate(df.index)}
        episodes = []
        ep_id = 0
        prev_pos = None
        for row in rows:
            t = pd.Timestamp(row["date"])
            pos = trading_positions.get(t)
            if prev_pos is None or (pos - prev_pos) > 5:
                ep_id += 1
                episodes.append({"episode_id": ep_id, "dates": [row["date"]], "drops": [row["pct_chg"]]})
            else:
                episodes[-1]["dates"].append(row["date"])
                episodes[-1]["drops"].append(row["pct_chg"])
            prev_pos = pos
        for ep in episodes:
            start = pd.Timestamp(ep["dates"][0])
            i0 = trading_positions[start]
            base = float(close.iloc[i0 - 1]) if i0 >= 1 else float(close.iloc[i0])
            end = pd.Timestamp(ep["dates"][-1])
            i1 = trading_positions[end]
            ep["n_days"] = len(ep["dates"])
            ep["cum_drop_pct"] = round((float(close.iloc[i1]) / base - 1) * 100, 2)
            ep["start"] = ep["dates"][0]
            ep["end"] = ep["dates"][-1]

        # conditional statistics for the warning model
        def p_next5_bigdrop(mask):
            sub = ret[mask]
            if len(sub) == 0:
                return None, 0
            hits = 0
            for t in sub.index:
                i = df.index.get_loc(t)
                window = ret.iloc[i + 1: i + 6]
                if len(window) and (window <= -0.015).any():
                    hits += 1
            return round(hits / len(sub) * 100, 1), int(len(sub))

        def p_same_day_drop(mask_on_us):
            # mask defined on US session dates; mapped to NEXT A-share session
            hits, total = 0, 0
            for us_t, r in mask_on_us.items():
                nxt = ret.index[ret.index > us_t]
                if len(nxt) == 0:
                    continue
                t = nxt[0]
                total += 1
                if pd.notna(ret.loc[t]) and ret.loc[t] <= -0.015:
                    hits += 1
            return round(hits / total * 100, 1) if total else None, total

        base_all, n_all = p_next5_bigdrop(pd.Series(True, index=ret.index))
        base_dropday_rate = round(float((ret <= -0.015).mean() * 100), 2)

        us_rets = {k: v.pct_change() for k, v in us_close.items()}
        cond = {}
        for k, s in us_rets.items():
            if len(s) == 0:
                continue
            for th in (-0.01, -0.015, -0.02):
                p, n = p_same_day_drop(s[s <= th])
                cond[f"overnight_{k}_le_{abs(th)*100:.1f}pct"] = {"p_star50_drop_same_day_pct": p, "n": n}

        trend_mask = close < ma60
        p_trend, n_trend = p_next5_bigdrop(trend_mask.fillna(False))
        hot_mask = (mom20 > 0.10) & (vol_ratio > 1.2)
        p_hot, n_hot = p_next5_bigdrop(hot_mask.fillna(False))
        veryhot_mask = mom20 > 0.15
        p_veryhot, n_veryhot = p_next5_bigdrop(veryhot_mask.fillna(False))
        two_down = (ret < 0) & (ret.shift(1) < 0)
        p_twodown, n_twodown = p_next5_bigdrop(two_down.fillna(False))
        calm_mask = (mom20.abs() <= 0.05) & (vol_ratio.fillna(1) < 1.1)
        p_calm, n_calm = p_next5_bigdrop(calm_mask.fillna(False))

        fwd = dd_df[["fwd_1d", "fwd_5d", "fwd_20d"]].astype(float)
        all_f5 = (close.shift(-5) / close - 1).dropna() * 100

        by_year = {}
        for row in rows:
            y = row["date"][:4]
            by_year.setdefault(y, {"count": 0, "drops": []})
            by_year[y]["count"] += 1
            by_year[y]["drops"].append(row["pct_chg"])
        for y, v in by_year.items():
            drops = v.pop("drops")
            v["avg_drop_pct"] = round(float(np.mean(drops)), 2)
            v["worst_drop_pct"] = min(drops) if drops else None

        buckets = {"-1.5~-2": 0, "-2~-3": 0, "-3~-4": 0, "<-4": 0}
        for row in rows:
            d = row["pct_chg"]
            if d > -2:
                buckets["-1.5~-2"] += 1
            elif d > -3:
                buckets["-2~-3"] += 1
            elif d > -4:
                buckets["-3~-4"] += 1
            else:
                buckets["<-4"] += 1

        qqq_on = [row["overnight_qqq"] for row in rows if row["overnight_qqq"] is not None]
        soxx_on = [row["overnight_soxx"] for row in rows if row["overnight_soxx"] is not None]
        summary = {
            "star_code": star,
            "window": {"start": str(df.index[0].date()), "end": str(df.index[-1].date()), "n_days": int(len(df))},
            "drop_days": {"count": len(rows), "share_pct": base_dropday_rate},
            "by_year": by_year,
            "bucket_dist": buckets,
            "episodes": {"count": len(episodes), "multi_day": sum(1 for e in episodes if e["n_days"] > 1)},
            "fwd_after_drop_days": {
                "fwd_1d_median": round(float(fwd["fwd_1d"].median()), 2) if len(fwd) else None,
                "fwd_5d_median": round(float(fwd["fwd_5d"].median()), 2) if len(fwd) else None,
                "fwd_20d_median": round(float(fwd["fwd_20d"].median()), 2) if len(fwd) else None,
                "fwd_5d_median_baseline_all_days": round(float(all_f5.median()), 2),
            },
            "overnight_us_on_drop_days": {
                "qqq_median": round(float(np.median(qqq_on)), 2) if qqq_on else None,
                "qqq_le_minus1_share": round(float(np.mean([x <= -1 for x in qqq_on]) * 100), 1) if qqq_on else None,
                "soxx_median": round(float(np.median(soxx_on)), 2) if soxx_on else None,
                "soxx_le_minus2_share": round(float(np.mean([x <= -2 for x in soxx_on]) * 100), 1) if soxx_on else None,
            },
            "model_calibration": {
                "p_next5_bigdrop_all_days": {"pct": base_all, "n": n_all},
                "p_next5_bigdrop_below_ma60": {"pct": p_trend, "n": n_trend},
                "p_next5_bigdrop_hot_mom20gt10_volratio12": {"pct": p_hot, "n": n_hot},
                "p_next5_bigdrop_mom20gt15": {"pct": p_veryhot, "n": n_veryhot},
                "p_next5_bigdrop_two_down_days": {"pct": p_twodown, "n": n_twodown},
                "p_next5_bigdrop_calm_regime": {"pct": p_calm, "n": n_calm},
                "overnight_us_conditions": cond,
            },
        }

        dd_df.to_csv(os.path.join(out_dir, "drop_days.csv"), index=False)
        pd.DataFrame(episodes).to_csv(os.path.join(out_dir, "episodes.csv"), index=False)
        with open(os.path.join(out_dir, "summary.json"), "w") as f:
            json.dump(summary, f, ensure_ascii=False, indent=1)

        extra_dir = os.path.join(os.getcwd(), "src", "skills", ".study_cache")
        try:
            os.makedirs(extra_dir, exist_ok=True)
            dd_df.to_csv(os.path.join(extra_dir, "drop_days.csv"), index=False)
            pd.DataFrame(episodes).to_csv(os.path.join(extra_dir, "episodes.csv"), index=False)
            with open(os.path.join(extra_dir, "summary.json"), "w") as f:
                json.dump(summary, f, ensure_ascii=False, indent=1)
            print("STUDY_CACHE_OK")
        except Exception as exc:
            print("STUDY_CACHE_FAIL=%r" % exc)

        print("ARTIFACT_DIR=%s" % os.path.abspath(out_dir))
        print("DROPDAYS_CSV_BEGIN")
        print(dd_df.to_csv(index=False))
        print("DROPDAYS_CSV_END")
        print("EPISODES_JSON=" + json.dumps(episodes, ensure_ascii=False))
        print("DROP_DAYS=%d EPISODES=%d" % (len(rows), len(episodes)))
        print("SUMMARY=" + json.dumps(summary, ensure_ascii=False))

        sig = pd.Series(1.0, index=df.index)
        sig[(ret <= -0.015).shift(1).fillna(False)] = 0.0
        sig = sig.fillna(1.0)

        sig_loader = sig.reindex(pd.to_datetime(pd.Index(data_map[star].index))).fillna(1.0)
        out = {star: sig_loader}
        for code, d in data_map.items():
            if str(code).upper().endswith(".US"):
                idx = pd.to_datetime(pd.Index(d.index))
                out[code] = pd.Series(1.0, index=idx)
        return out
