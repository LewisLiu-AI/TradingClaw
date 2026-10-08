#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""科创50 单日大跌利空归因 + 预警模型 HTML 报告生成器."""
import csv
import json
import os
from collections import defaultdict
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(BASE, "artifacts")
ATTR = os.path.join(BASE, "attribution_raw")
OUT_HTML = os.path.join(BASE, "科创50单日大跌利空归因与预警模型.html")

CATEGORIES = ["海外传导", "中美与地缘", "政策监管", "宏观流动性", "板块自身", "技术性回调"]
CAT_COLOR = {
    "海外传导": "#3b82f6",
    "中美与地缘": "#ef4444",
    "政策监管": "#f59e0b",
    "宏观流动性": "#8b5cf6",
    "板块自身": "#10b981",
    "技术性回调": "#94a3b8",
}
YEAR_THEMES = {}


def load_data():
    with open(os.path.join(ART, "summary.json")) as f:
        summary = json.load(f)
    drop_days = []
    with open(os.path.join(ART, "drop_days.csv")) as f:
        for row in csv.DictReader(f):
            row["pct_chg"] = float(row["pct_chg"])
            row["close"] = float(row["close"])
            for k in ("mom_20d", "vol_ratio_20", "overnight_qqq", "overnight_soxx", "fwd_1d", "fwd_5d", "fwd_20d"):
                row[k] = float(row[k]) if row.get(k) else None
            drop_days.append(row)
    episodes = []
    with open(os.path.join(ART, "episodes.csv")) as f:
        for row in csv.DictReader(f):
            episodes.append({
                "episode_id": int(row["episode_id"]),
                "dates": eval(row["dates"]),
                "drops": eval(row["drops"]),
                "n_days": int(row["n_days"]),
                "cum_drop_pct": float(row["cum_drop_pct"]),
                "start": row["start"],
                "end": row["end"],
            })
    # index close series
    index_series = []
    star_csv = "/tmp/star50_index.csv"
    alt = os.path.join(BASE, "star50_index.csv")
    path = star_csv if os.path.exists(star_csv) else alt
    with open(path) as f:
        for row in csv.DictReader(f):
            index_series.append([row["date"], float(row["close"])])
    # attribution
    attr = {}
    year_summaries = {}
    if os.path.isdir(ATTR):
        for fn in sorted(os.listdir(ATTR)):
            if fn.endswith(".json"):
                year = fn[:-5]
                with open(os.path.join(ATTR, fn)) as f:
                    items = json.load(f)
                for it in items:
                    attr[it["episode_id"]] = it
            elif fn.endswith("_summary.txt"):
                year_summaries[fn[:-12]] = open(os.path.join(ATTR, fn)).read().strip()
    return summary, drop_days, episodes, index_series, attr, year_summaries


def fmt_pct(v, nd=2):
    return ("—" if v is None else f"{v:.{nd}f}")




CASES = [
    {
        "id": 1,
        "title": "2020-07-15 ~ 07-24：中芯国际IPO抽血 + 首批解禁 + 领事馆风暴",
        "drop": "簇跌幅 -18.35%（单日最深 -8.82%）",
        "cat": "板块自身 | 中美与地缘",
        "body": "科创50发布后的首场压力测试，三重利空在同一窗口叠加：<b>① 巨无霸抽血</b>——7月16日中芯国际科创板上市，首日成交约480亿元虹吸全场，科创50单日-8.82%（发布以来最大单日跌幅之一）；<b>② 首批解禁</b>——科创板开板一周年迎来限售股解禁潮，减持预期压制估值；<b>③ 地缘冲击</b>——7月24日中美互关领事馆后的首个完整交易日，北向资金净流出163亿元，科创50再挫-7.02%。启示：高估值板块对'资金分流'类利空的敏感度远超基本面利空。",
        "ep": 1,
    },
    {
        "id": 2,
        "title": "2024-01-17 ~ 02-02：雪球集中敲入 + 量化DMA强平的流动性踩踏",
        "drop": "簇跌幅 -13.38%（单日最深 -3.79%）",
        "cat": "宏观流动性",
        "body": "教科书级的衍生品/杠杆负反馈：1月22日中证500/1000挂钩雪球产品集中敲入（估算约513亿+289亿规模），沪指-2.68%创三年最大跌幅；随后量化DMA高杠杆持仓强平、微盘股流动性枯竭，1月26日至2月2日连续踩踏（1-30最重）。经济悲观预期只是放大器，<b>真正的下跌引擎是杠杆结构的强制出清</b>。启示：'价格接近敲入线/杠杆强平区'本身就是利空，预警模型必须包含杠杆资金监测（D1因子权重最高的原因）。",
        "ep": 55,
    },
    {
        "id": 3,
        "title": "2024-10-09 ~ 10-16：'9·24'暴涨后的获利回吐与政策预期落空",
        "drop": "簇跌幅 -14.48%（10-11单日 -5.79%）",
        "cat": "政策监管（卖事实）",
        "body": "9月24日政策组合拳后科创50在6个交易日内暴涨约45-50%，进入本报告测得的最强预警状态（20日涨幅>15%，未来5日大跌概率78.6%）。节后10月8日天量冲高回落，发改委发布会未给出市场期待的增量财政，10-10/11连续两日跌超4%，10-15/16缩量续跌。<b>急涨本身制造了下跌的势能</b>——拥挤度顶格+事件催化不及预期=最大回撤组合。启示：暴涨后的'利好兑现卖事实'必须触发模型红色区间（E1+C1共振）。",
        "ep": 64,
    },
    {
        "id": 4,
        "title": "2025-04-07：'对等关税'全球股灾（历史最大单日跌幅）",
        "drop": "单日 -9.22%",
        "cat": "中美与地缘",
        "body": "4月2日美国宣布超预期的'对等关税'（对华34%+），全球风险资产崩盘；4月7日A股全线重挫（上证-7.34%、创业板-12.5%），科创50单日-9.22%创发布以来纪录，随后中央汇金宣布增持ETF护盘、市场逐步修复。这是纯外生政策冲击的典型：事前无法预测具体日期，但模型可在<b>摩擦升级的72小时窗口（B1因子+3分）</b>与高位拥挤状态叠加时提前进入红色警戒。启示：地缘/关税类利空无法回避，只能靠仓位纪律应对。",
        "ep": 75,
    },
    {
        "id": 5,
        "title": "2024-07-23 ~ 08-05：半导体抱团瓦解 → 日元套息平仓全球股灾",
        "drop": "簇跌幅 -6.34%（单日最深 -4.11%）",
        "cat": "板块自身 | 海外传导",
        "body": "两段式下跌的范本：7月23日LPR降息利好兑现当日，中芯/寒武纪/海光等权重集体跌超5%，科创50放量-4.11%——高位抱团瓦解；随后8月2日隔夜美股科技股暴雷大跌、8月5日日元套息交易平仓引发全球股灾（日经单日-12.4%），科创50再挫-2.94%。<b>内部拥挤度出清与海外risk-off的接力</b>，是'板块自身+海外传导'复合利空的完整样本。",
        "ep": 62,
    },
    {
        "id": 6,
        "title": "2022-03-03 ~ 04-26：俄乌战争 + 疫情封控 + 中概退市 + 汇率急贬",
        "drop": "簇跌幅 -29.44%（单日最深 -6.13%）",
        "cat": "中美与地缘 | 宏观流动性",
        "body": "17个交易日、累计-29.44%的系统性崩塌，四大利空接力：3月上旬俄乌战争+油价飙升；3月中旬中概股《外国公司问责法》退市清单引发外资撤离A股映射；4月上海疫情封控冲击供应链与经济预期；4月下旬人民币对美元急贬破6.6、4-25上证-5.13%恐慌宣泄。此后金稳会喊话+疫情缓解才完成筑底。<b>多重宏观利空共振时，任何单因子预警都不够，必须看总分级别</b>。",
        "ep": 28,
    },
    {
        "id": 7,
        "title": "2026-07-10 ~ 08-03：AI硬件全球去泡沫——2255新高后10日崩跌29%",
        "drop": "簇跌幅 -28.96%（单日最深 -7.12%）",
        "cat": "板块自身 | 海外传导",
        "body": "科创50于7月1日创2255.25点历史新高（上半年累涨64.25%），随后四波利空接力崩塌：<b>① Meta转售过剩算力</b>（7/2单日-7.7%，'AI资本开支见顶'恐慌）+长鑫科技579亿超级IPO打新分流；<b>② 全球存储链崩塌</b>——7/16韩国央行加息25bp，KOSPI-6%、SK海力士-12%，7/17科创50-7.12%恐慌极值、存储/PCB/CPO跌停潮、电子单日净流出500亿；<b>③ 英伟达7500亿美元'循环融资'计划</b>（7/28黑色星期二）引发AI融资链担忧，KOSPI单日-10.84%，科创50-6.33%；<b>④ 筹码出清未完成</b>——公募高仓位逆势加仓、固收+仓位三年新高，8月初继续阴跌。托底面：7月股票ETF净流入4360亿元'越跌越买'，但未能扭转趋势。启示：成交集中度（前5%个股占比48%）、权重集中度（寒武纪单票15%）、两融与机构仓位分位是本轮最有效的领先指标——拥挤度因子E1在本案例前2-4周即给出顶格信号。",
        "ep": 89,
    },
]


def case_cards_html(attr):
    parts = []
    for c in CASES:
        a = attr.get(c["ep"])
        note = "" if a else '<p class="small">⏳ 该事件簇的独立检索归因仍在进行，卡片内容基于已知公开事实，稍后将由检索结果校验。</p>'
        parts.append(f"""
<div class="case">
  <h4><span class="tag">{c['drop']}</span> {c['title']}</h4>
  <p style="margin-top:6px"><span class="chip" style="--c:{CAT_COLOR.get(c['cat'].split(' ')[0], '#94a3b8')}">{c['cat']}</span></p>
  <p>{c['body']}</p>
  {note}
</div>""")
    return "".join(parts)


def main():
    summary, drop_days, episodes, index_series, attr, year_summaries = load_data()
    years = sorted({e["start"][:4] for e in episodes})

    # ---------- stats ----------
    # 组合类目（"A | B"）按主类（首项）归一计入统计与配色，保证六类合计 = 簇总数
    def cat_primary(cat):
        return cat.split(" | ")[0].strip() if cat else cat

    cat_count = defaultdict(int)
    cat_deep = defaultdict(int)  # cum_drop <= -8 or any day <= -4
    cat_by_year = defaultdict(lambda: defaultdict(int))
    for e in episodes:
        a = attr.get(e["episode_id"])
        if not a:
            continue
        cat = cat_primary(a.get("category", "未归类"))
        cat_count[cat] += 1
        year = e["start"][:4]
        cat_by_year[year][cat] += 1
        if e["cum_drop_pct"] <= -8 or min(e["drops"]) <= -4:
            cat_deep[cat] += 1

    # recovery by category
    cat_fwd = defaultdict(list)
    for dd in drop_days:
        a = None
        # find episode attribution by date
        for e in episodes:
            if dd["date"] in e["dates"]:
                a = attr.get(e["episode_id"])
                break
        if a and dd["fwd_5d"] is not None:
            cat_fwd[cat_primary(a.get("category", "未归类"))].append(dd["fwd_5d"])
    cat_fwd5_median = {c: sorted(v)[len(v) // 2] for c, v in cat_fwd.items() if v}

    deep_episodes = [e for e in episodes if e["cum_drop_pct"] <= -8 or min(e["drops"]) <= -4]
    top_days = sorted(drop_days, key=lambda r: r["pct_chg"])[:12]

    covered = sum(1 for e in episodes if e["episode_id"] in attr)
    high_conf = sum(1 for a in attr.values() if a.get("confidence") == "高")
    tech_share = cat_count.get("技术性回调", 0) / max(covered, 1) * 100

    # ---------- build JSON payloads for charts ----------
    payload = {
        "indexSeries": index_series,
        "dropMarkers": [
            {"name": d["date"], "value": [d["date"], d["close"]], "pct": d["pct_chg"]}
            for d in drop_days
        ],
        "episodes": [
            {
                "id": e["episode_id"],
                "start": e["start"],
                "end": e["end"],
                "cum": e["cum_drop_pct"],
                "n": e["n_days"],
                "cat": cat_primary(attr.get(e["episode_id"], {}).get("category", "未归类")),
            }
            for e in episodes
        ],
        "catCountAll": {c: cat_count.get(c, 0) for c in CATEGORIES},
        "catCountDeep": {c: cat_deep.get(c, 0) for c in CATEGORIES},
        "catByYear": {
            y: {c: cat_by_year[y].get(c, 0) for c in CATEGORIES} for y in years
        },
        "calib": summary.get("model_calibration", {}),
        "catFwd5": cat_fwd5_median,
    }

    # ---------- attribution table rows ----------
    ep_rows = []
    for e in episodes:
        a = attr.get(e["episode_id"])
        cat = a["category"] if a else "待归因"
        color = CAT_COLOR.get(cat_primary(cat), "#cbd5e1")
        catalyst = a["catalyst"] if a else "研究中"
        detail = a["detail"] if a else ""
        conf = a.get("confidence", "") if a else ""
        src_html = ""
        if a:
            links = []
            for i, u in enumerate(a.get("sources", [])[:3]):
                links.append(f'<a href="{u}" target="_blank" rel="noopener">[{i+1}]</a>')
            src_html = " ".join(links)
        worst = min(e["drops"])
        ep_rows.append(f"""
<tr>
  <td class="mono">{e['start']}<br><span class="dim">~{e['end']}</span></td>
  <td class="mono">{e['n_days']}天</td>
  <td class="mono {'neg' if e['cum_drop_pct']<0 else ''}">{e['cum_drop_pct']:.2f}%</td>
  <td class="mono">最狠 {worst:.2f}%</td>
  <td><span class="chip" style="--c:{color}">{cat}</span></td>
  <td class="cat-cell"><b>{catalyst}</b><br><span class="dim">{detail}</span> {src_html}</td>
  <td class="mono">{conf}</td>
</tr>""")

    day_rows = []
    for d in drop_days:
        a = None
        for e in episodes:
            if d["date"] in e["dates"]:
                a = attr.get(e["episode_id"])
                break
        cat = a["category"] if a else ""
        color = CAT_COLOR.get(cat_primary(cat), "#cbd5e1")
        qqq = d["overnight_qqq"]
        soxx = d["overnight_soxx"]
        day_rows.append(f"""
<tr>
  <td class="mono">{d['date']}</td>
  <td class="mono neg">{d['pct_chg']:.2f}%</td>
  <td class="mono {'neg' if (qqq or 0) < 0 else ''}">{fmt_pct(qqq)}%</td>
  <td class="mono {'neg' if (soxx or 0) < 0 else ''}">{fmt_pct(soxx)}%</td>
  <td class="mono">{fmt_pct(d['fwd_5d'])}%</td>
  <td class="mono">{fmt_pct(d['fwd_20d'])}%</td>
  <td><span class="chip" style="--c:{color}">{cat or '·'}</span></td>
</tr>""")

    top_rows = []
    for d in top_days:
        a = None
        for e in episodes:
            if d["date"] in e["dates"]:
                a = attr.get(e["episode_id"])
                break
        cat = a["category"] if a else ""
        color = CAT_COLOR.get(cat_primary(cat), "#cbd5e1")
        top_rows.append(f"""
<tr>
  <td class="mono">{d['date']}</td>
  <td class="mono neg"><b>{d['pct_chg']:.2f}%</b></td>
  <td class="mono">{d['close']:.0f}</td>
  <td><span class="chip" style="--c:{color}">{cat or '待归因'}</span></td>
  <td>{a['catalyst'] if a else '研究中'}</td>
</tr>""")

    year_theme_html = ""
    for y in years:
        s = year_summaries.get(y, "")
        if s:
            year_theme_html += f'<div class="year-theme"><b>{y}</b><p>{s}</p></div>'

    calib = summary["model_calibration"]
    calib_rows = [
        ("任意交易日（基准）", calib["p_next5_bigdrop_all_days"], ""),
        ("指数处于60日均线下方（下行趋势）", calib["p_next5_bigdrop_below_ma60"], "趋势走弱并不显著增加大跌概率——跌势中反而钝化"),
        ("过热：20日涨幅>10% 且 放量(量比>1.2)", calib["p_next5_bigdrop_hot_mom20gt10_volratio12"], "最强预警状态：较基准提升28.6个百分点"),
        ("急涨：20日涨幅>15%", calib["p_next5_bigdrop_mom20gt15"], "连续急涨后5日内出现≥1.5%大跌概率近8成"),
        ("已连跌两日", calib["p_next5_bigdrop_two_down_days"], "与基准几乎相同——连跌不是额外信号"),
        ("平静期：|20日涨幅|≤5% 且 缩量", calib["p_next5_bigdrop_calm_regime"], "低波动状态并无保护作用"),
    ]
    calib_html = "".join(
        f"<tr><td>{n}</td><td class='mono'><b>{d['pct']}%</b></td><td class='mono dim'>n={d['n']}</td><td class='dim'>{note}</td></tr>"
        for n, d, note in calib_rows
    )
    def _us_label(k):
        idx = k.split("_le_")[1].replace("pct", "")
        name = "隔夜纳指(QQQ)" if "qqq" in k else "隔夜费半(SOXX)"
        return f"{name} ≤ -{idx}%"

    us_rows = "".join(
        f"<tr><td>{_us_label(k)}</td>"
        f"<td class='mono'><b>{v['p_star50_drop_same_day_pct']}%</b></td><td class='mono dim'>n={v['n']}</td></tr>"
        for k, v in calib["overnight_us_conditions"].items()
    )

    html = render_html(
        summary=summary, payload=json.dumps(payload, ensure_ascii=False),
        ep_rows="".join(ep_rows), day_rows="".join(day_rows), top_rows="".join(top_rows),
        calib_html=calib_html, us_rows=us_rows, year_theme_html=year_theme_html,
        covered=covered, high_conf=high_conf, tech_share=f"{tech_share:.0f}",
        n_days=summary["window"]["n_days"],
        deep_n=len(deep_episodes), years=years,
        case_cards=case_cards_html(attr),
        cat_fwd5=cat_fwd5_median,
    )
    with open(OUT_HTML, "w") as f:
        f.write(html)
    print("written:", OUT_HTML, len(html), "chars")


def render_html(**kw):
    from template import TEMPLATE
    out = TEMPLATE
    for k, v in kw.items():
        out = out.replace("__" + k.upper() + "__", str(v))
    return out


if __name__ == "__main__":
    main()
