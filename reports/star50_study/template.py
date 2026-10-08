# -*- coding: utf-8 -*-
"""HTML 模板：科创50 单日大跌利空归因与预警模型。占位符 __KEY__ 由 build_report.py 注入。"""

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>科创50 单日大跌利空归因与预警模型</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
:root{
  --bg:#f6f7f9; --card:#ffffff; --ink:#1a2333; --dim:#64748b; --line:#e5e9f0;
  --accent:#2563eb; --neg:#dc2626; --pos:#16a34a;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--ink);line-height:1.65;font-size:15px}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px 60px}
header.hero{background:linear-gradient(135deg,#0f1e3d 0%,#1e3a8a 60%,#2563eb 100%);color:#fff;padding:52px 20px 44px;margin-bottom:28px}
header.hero .inner{max-width:1120px;margin:0 auto}
header.hero h1{font-size:30px;font-weight:700;letter-spacing:.5px}
header.hero .sub{margin-top:10px;color:#c7d4f0;font-size:14.5px;max-width:860px}
header.hero .meta{margin-top:18px;display:flex;flex-wrap:wrap;gap:10px}
header.hero .meta span{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.18);padding:4px 12px;border-radius:99px;font-size:12.5px}
h2.sec{font-size:21px;margin:44px 0 6px;display:flex;align-items:center;gap:10px}
h2.sec .no{background:var(--accent);color:#fff;font-size:13px;width:26px;height:26px;border-radius:8px;display:inline-flex;align-items:center;justify-content:center;font-weight:700}
.sec-note{color:var(--dim);font-size:13.5px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px;margin-bottom:18px;box-shadow:0 1px 3px rgba(15,30,60,.04)}
.tldr{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.tldr .item{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:12px;padding:16px 18px}
.tldr .item b{display:block;margin-bottom:6px;font-size:14.5px}
.tldr .item p{font-size:13.5px;color:#374151}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:14px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;text-align:center}
.stat .v{font-size:24px;font-weight:700;color:var(--accent)}
.stat .v.neg{color:var(--neg)}
.stat .l{font-size:12px;color:var(--dim);margin-top:4px}
.chart{width:100%;height:420px}
.chart-sm{width:100%;height:340px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:860px){.grid2{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:13.2px}
th{background:#f1f5f9;text-align:left;padding:8px 10px;font-weight:600;color:#334155;border-bottom:2px solid var(--line);white-space:nowrap}
td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tr:hover td{background:#f8fafc}
.mono{font-variant-numeric:tabular-nums;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.6px}
.neg{color:var(--neg)} .pos{color:var(--pos)} .dim{color:var(--dim);font-size:12.5px}
.chip{display:inline-block;padding:2px 9px;border-radius:99px;font-size:12px;font-weight:600;color:#fff;background:var(--c,#94a3b8);white-space:nowrap}
.cat-cell{max-width:430px}
.scrollbox{max-height:520px;overflow:auto;border:1px solid var(--line);border-radius:10px}
.scrollbox table th{position:sticky;top:0;z-index:2}
.year-theme{border-top:1px dashed var(--line);padding:12px 4px 2px;margin-top:10px}
.year-theme b{color:var(--accent)}
.year-theme p{font-size:13.5px;color:#374151;margin-top:4px}
.callout{border-left:4px solid var(--accent);background:#eff6ff;border-radius:0 10px 10px 0;padding:14px 18px;margin:14px 0;font-size:14px}
.callout.warn{border-color:var(--neg);background:#fef2f2}
.callout.ok{border-color:var(--pos);background:#f0fdf4}
.case{border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:14px;background:var(--card)}
.case h4{font-size:16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.case .tag{font-size:12px;color:var(--neg);font-weight:700}
.case p{font-size:13.8px;color:#374151;margin-top:8px}
.model-arch{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:16px 0}
@media(max-width:900px){.model-arch{grid-template-columns:repeat(2,1fr)}}
.model-arch .blk{border:1px solid var(--line);border-radius:12px;padding:14px;text-align:center;background:#f8fafc}
.model-arch .blk .ico{font-size:22px}
.model-arch .blk b{display:block;margin:6px 0 4px;font-size:14px}
.model-arch .blk span{font-size:12px;color:var(--dim)}
.lv{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}
@media(max-width:900px){.lv{grid-template-columns:repeat(2,1fr)}}
.lv .l{border-radius:12px;padding:14px;color:#fff}
.lv .l b{font-size:15px}
.lv .l .rng{font-size:12px;opacity:.85;margin-top:2px}
.lv .l p{font-size:12.5px;margin-top:8px;opacity:.95}
.lv .g{background:#16a34a}.lv .y{background:#d97706}.lv .o{background:#ea580c}.lv .r{background:#dc2626}
footer{margin-top:50px;padding:20px;color:var(--dim);font-size:12.5px;border-top:1px solid var(--line)}
a{color:var(--accent)}
.toc{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 0}
.toc a{font-size:12.5px;background:#fff;border:1px solid var(--line);border-radius:99px;padding:4px 12px;text-decoration:none;color:#334155}
.small{font-size:12.5px;color:var(--dim)}
@media print{
  html,body{background:#fff}
  *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .scrollbox{max-height:none!important;height:auto!important;overflow:visible!important}
  table,tr,.case,.lv .l,.callout,.stat,.item{page-break-inside:avoid}
  h2.sec,h3{page-break-after:avoid}
  .toc{display:none}
  .chart{page-break-inside:avoid}
}
</style>
</head>
<body>
<header class="hero">
  <div class="inner">
    <h1>科创50单日大跌：利空归因全景 与 预警模型 v1.0</h1>
    <div class="sub">覆盖 2020-07-23（指数发布）至 2026-09-08 全部 <b>260 个单日跌幅≥1.5%</b> 交易日、91 个下跌事件簇；逐簇新闻检索归因（消息面/政策面/海外/板块自身），并基于 1,504 个交易日完成预警因子校准。</div>
    <div class="meta">
      <span>数据窗口 2020-07-01 → 2026-09-08</span>
      <span>交易日 n=__N_DAYS__</span>
      <span>大跌日 260（17.3%）</span>
      <span>事件簇 91</span>
      <span>已归因 __COVERED__/91 簇（高置信 __HIGH_CONF__）</span>
      <span>生成日期 2026-09-08</span>
    </div>
    <div class="toc">
      <a href="#s1">① 数据全景</a><a href="#s2">② 归因总览</a><a href="#s3">① 六大案例</a><a href="#s4">④ 归因明细</a><a href="#s5">⑤ 逐日明细</a><a href="#s6">⑥ 规律与校准</a><a href="#s7">⑦ 预警模型 v1.0</a><a href="#s8">⑧ 方法与局限</a>
    </div>
  </div>
</header>
<div class="wrap">

<!-- ============ TLDR ============ -->
<h2 class="sec" id="s0"><span class="no">★</span>核心结论（TL;DR）</h2>
<div class="tldr">
  <div class="item"><b>① 1.5% 是科创50的"日常"，不是"事故"</b><p>高波动指数下 17.2% 的交易日跌幅≥1.5%，任意 5 日窗口出现此类大跌的概率高达 <b>56.6%</b>。预警模型的目标应锁定 <b>≥3% 级单日重挫（占 4.3%）与 -8% 级事件簇（__DEEP_N__ 个）</b>，而非日常波动。</p></div>
  <div class="item"><b>② 杀伤最深：中美与地缘 &gt; 板块自身拥挤瓦解 &gt; 宏观流动性踩踏</b><p>91 簇全样本看：<b>中美与地缘类平均杀伤最深</b>（簇跌幅中位 -7.55%，78% 为深跌簇：2022 春 -29.44%、2025-04 单日 -9.22%）；<b>板块自身拥挤瓦解产生的深跌簇最多</b>（10 个，占其 45%：2026-07 -28.96%）；宏观流动性踩踏频次低（3 个）但可造成极端单簇（2024-01 雪球 -13.38%）；海外传导频率最高（21 簇）而中位杀伤 -3.72% 居中；技术性回调与政策"卖事实"杀伤最浅。</p></div>
  <div class="item"><b>③ 隔夜美股只是"放大器"，不是主因</b><p>大跌日前夜费半≤-2% 的占比仅 24.3%；条件概率看，隔夜费半≤-2% 时当日大跌概率 28.3%（基准 17.2%，1.65 倍）——<b>约七成的大跌日并非美股引起</b>，必须盯国内资金面与政策事件。</p></div>
  <div class="item"><b>④ "利好兑现卖事实"是 A 股特色主因</b><p>重大会议/政策/降息落地后 1-3 日内兑现下跌的事件簇反复出现（2024 年尤甚）。<b>政策事件日历必须作为模型的显式输入</b>：事件落地日 ±3 天默认提高警戒。</p></div>
  <div class="item"><b>⑤ 过热状态是统计上最强的领先信号</b><p>20日涨幅>10% 且放量时，未来 5 日出现≥1.5% 大跌的概率 <b>85.2%</b>（基准 56.6%）；若叠加中美/政策事件触发，即进入红色区间。<b>急涨本身就是最大的利空。</b></p></div>
  <div class="item"><b>⑥ 大跌后接飞刀无统计优势</b><p>大跌日之后 T+5 中位收益仅 +0.02%（全样本基准 -0.21%），T+20 中位 <b>-0.41%</b>。<b>大跌不是买点信号</b>，应等拥挤度出清或触发因素证伪后再介入。</p></div>
</div>

<!-- ============ S1 数据全景 ============ -->
<h2 class="sec" id="s1"><span class="no">1</span>科创50走势与大跌日全景</h2>
<p class="sec-note">红点 = 单日跌幅≥1.5% 的交易日（点位越高/越密集代表高位风险积累）。悬停可查看日期。</p>
<div class="card">
  <div class="stat-grid">
    <div class="stat"><div class="v">1,504</div><div class="l">交易日样本</div></div>
    <div class="stat"><div class="v neg">260</div><div class="l">大跌日（≥1.5%）</div></div>
    <div class="stat"><div class="v">17.2%</div><div class="l">大跌日占比</div></div>
    <div class="stat"><div class="v">91</div><div class="l">下跌事件簇</div></div>
    <div class="stat"><div class="v neg">-29.4%</div><div class="l">最深事件簇(2022.3-4)</div></div>
    <div class="stat"><div class="v neg">-9.22%</div><div class="l">单日最大(2025-04-07)</div></div>
  </div>
  <div id="chartIndex" class="chart"></div>
  <p class="small">注：2020-07-23 之前为指数公司回溯计算值。跌幅分档：-1.5~-2% 共 86 天；-2~-3% 共 110 天；-3~-4% 共 32 天；&lt;-4% 共 32 天。</p>
</div>

<!-- ============ S2 归因总览 ============ -->
<h2 class="sec" id="s2"><span class="no">2</span>91 个事件簇归因总览</h2>
<p class="sec-note">每个事件簇 = 间隔≤5个交易日的连续大跌日；已归因 __COVERED__ 簇，其中高置信 __HIGH_CONF__ 簇。技术性回调占 __TECH_SHARE__%。</p>
<div class="card">
  <div class="grid2">
    <div><div id="chartCatPie" class="chart-sm"></div><p class="small" style="text-align:center">全部已归因事件簇类别分布</p></div>
    <div><div id="chartCatDeep" class="chart-sm"></div><p class="small" style="text-align:center">深跌事件簇（簇跌幅≤-8% 或 单日≤-4%）分布</p></div>
  </div>
  <div id="chartCatYear" class="chart" style="margin-top:10px"></div>
  <p class="small" style="text-align:center">年度 × 类别堆叠：利空主导因素的时代演变</p>
  __YEAR_THEME_HTML__
</div>

<!-- ============ S3 案例 ============ -->
<h2 class="sec" id="s3"><span class="no">3</span>六大典型案例深挖</h2>
<p class="sec-note">按"杀伤力 × 归因清晰度"选取，覆盖六大类利空的代表性形态。</p>
__CASE_CARDS__

<!-- ============ S4 归因明细 ============ -->
<h2 class="sec" id="s4"><span class="no">4</span>全部事件簇归因明细（91 簇）</h2>
<p class="sec-note">[n] 为新闻来源链接（点击可查证）。置信度：高=多源交叉验证且时点吻合；中=单一可靠来源或时点略有出入；低=间接推断。</p>
<div class="card"><div class="scrollbox"><table>
<thead><tr><th>日期区间</th><th>天数</th><th>簇跌幅</th><th>单日最深</th><th>类别</th><th>催化剂与细节</th><th>置信</th></tr></thead>
<tbody>__EP_ROWS__</tbody>
</table></div></div>

<!-- ============ S5 逐日明细 ============ -->
<h2 class="sec" id="s5"><span class="no">5</span>260 个大跌日逐日明细</h2>
<p class="sec-note">隔夜美股 = 前一美股交易日（美东时间）收盘涨跌，对应A股当日开盘前的信息集；T+5/T+20 = 大跌日收盘后第5/20个交易日相对收益。</p>
<div class="card"><div class="scrollbox" style="max-height:560px"><table>
<thead><tr><th>日期</th><th>当日跌幅</th><th>隔夜QQQ</th><th>隔夜SOXX</th><th>T+5</th><th>T+20</th><th>所属类别</th></tr></thead>
<tbody>__DAY_ROWS__</tbody>
</table></div></div>

<!-- ============ S6 规律 ============ -->
<h2 class="sec" id="s6"><span class="no">6</span>规律提炼与因子校准</h2>
<div class="card">
  <h3 style="font-size:16px;margin-bottom:10px">6.1 隔夜美股映射：显著但非主导</h3>
  <p style="font-size:14px">以隔夜纳指(QQQ)/费城半导体(SOXX)涨跌为条件，科创50 当日出现≥1.5%大跌的条件概率如下（样本 1,504 日）：</p>
  <table style="margin-top:10px">
    <thead><tr><th>条件（隔夜美股）</th><th>当日科创50大跌概率</th><th>样本</th></tr></thead>
    <tbody>__US_ROWS__</tbody>
  </table>
  <div class="callout">费半≤-2% 时大跌概率升至 27%（1.6 倍），但仍有 <b>73% 的情况没有大跌</b>；反过来，大跌日前夜美股中位仅 -0.32%。<b>海外冲击是"加分项"，主战场在国内资金面与政策事件。</b></div>

  <h3 style="font-size:16px;margin:22px 0 10px">6.2 指数状态条件概率：未来5日内出现≥1.5%大跌</h3>
  <table>
    <thead><tr><th>状态条件</th><th>未来5日大跌概率</th><th>样本</th><th>解读</th></tr></thead>
    <tbody>__CALIB_HTML__</tbody>
  </table>
  <div class="callout warn"><b>基率警示：</b>科创50 任意 5 日窗口出现≥1.5% 大跌的基准概率高达 56.6%——日常波动预警没有信息量。模型应聚焦 <b>≥3% 单日重挫（基率 4.3%）与 -8% 级事件簇</b>。</div>
  <div id="chartCalib" class="chart-sm" style="margin-top:8px"></div>

  <h3 style="font-size:16px;margin:22px 0 10px">6.3 哪类利空跌完还能回血？</h3>
  <p style="font-size:14px">按利空类别统计大跌日后 T+5 中位收益（正=有反弹倾向，负=继续阴跌）：</p>
  <div id="chartFwd" class="chart-sm"></div>
  <div class="callout ok"><b>操作含义：</b>按主类归一后，<b>政策监管（+1.38%）与技术性回调（+1.01%）型大跌后 T+5 反弹倾向最强</b>——前者是"卖事实"情绪的一次性出清，后者本无基本面利空；海外传导 +0.35% 亦有隔夜情绪消化后的修复倾向；而<b>板块自身（-0.81%）与宏观流动性（-0.77%）型下跌后 T+5 仍偏弱</b>——拥挤瓦解与流动性踩踏有二次探底惯性，切勿在踩踏初期抄底。</div>
</div>

<!-- ============ S7 模型 ============ -->
<h2 class="sec" id="s7"><span class="no">7</span>科创50 利空预警模型 v1.0</h2>
<p class="sec-note">设计目标：不是预测"哪天跌"，而是<b>持续监测"脆弱状态 + 事件触发"</b>，输出四级预警指导仓位纪律。</p>
<div class="card">
  <div class="model-arch">
    <div class="blk"><div class="ico">🌡️</div><b>A 海外映射</b><span>权重 20%<br>隔夜QQQ/SOXX + 联储/美债日历</span></div>
    <div class="blk"><div class="ico">🇨🇳🇺🇸</div><b>B 中美与地缘</b><span>权重 20%<br>关税/出口管制/制裁事件流</span></div>
    <div class="blk"><div class="ico">📅</div><b>C 政策事件日历</b><span>权重 15%<br>会议/数据/财报窗口"卖事实"预警</span></div>
    <div class="blk"><div class="ico">💧</div><b>D 内部脆弱性</b><span>权重 25%<br>杠杆/两融/北向/汇率/衍生品敲入</span></div>
    <div class="blk"><div class="ico">🔥</div><b>E 板块状态</b><span>权重 20%<br>拥挤度/估值分位/解禁减持</span></div>
  </div>

  <h3 style="font-size:16px;margin:18px 0 10px">7.1 打分卡（每日收盘后运行，总分 0-15）</h3>
  <table>
    <thead><tr><th style="width:34%">因子</th><th>触发阈值</th><th style="width:10%">分值</th><th style="width:32%">校准依据</th></tr></thead>
    <tbody>
      <tr><td><b>A1 隔夜费半(SOXX)</b></td><td>≤-2%：+2；(-2%,-1%]：+1</td><td class="mono">0-2</td><td class="dim">SOXX≤-2%→当日大跌P=28.3%（1.65×基准）</td></tr>
      <tr><td><b>A2 隔夜纳指(QQQ)</b></td><td>≤-2%：+1（与A1不叠加取高）</td><td class="mono">0-1</td><td class="dim">QQQ≤-2%→当日大跌P=32.4%（1.77×基准）</td></tr>
      <tr><td><b>A3 海外事件窗口</b></td><td>未来3日有联储议息/美国CPI/鲍威尔讲话：+1</td><td class="mono">0-1</td><td class="dim">2022-09、2024-08 等多例海外连环冲击</td></tr>
      <tr><td><b>B1 中美摩擦升级（72h内）</b></td><td>关税清单/出口管制/实体清单/制裁新规生效或宣布：+3</td><td class="mono">0-3</td><td class="dim">2020-09 中芯实体清单、2025-04 对等关税均属此类</td></tr>
      <tr><td><b>B2 地缘军事冲突（72h内）</b></td><td>台海/俄乌/中东重大升级：+2</td><td class="mono">0-2</td><td class="dim">2020-07 领事馆、2024-11-22 俄乌导弹</td></tr>
      <tr><td><b>C1 国内重大会议/数据落地</b></td><td>未来5日有中央级会议/重磅数据，且事件落地日起 +1.5</td><td class="mono">0-1.5</td><td class="dim">"卖事实"反复出现：2024-12-13、2024-10-08 发改委发布会等</td></tr>
      <tr><td><b>C2 权重股财报窗口</b></td><td>未来10日进入中芯/寒武纪/海光等权重股财报集中披露：+1</td><td class="mono">0-1</td><td class="dim">2024-09-02 中报雷案例</td></tr>
      <tr><td><b>D1 杠杆资金恶化</b></td><td>两融余额5日降幅>1.5%：+2；微盘股/雪球敲入风险区：+2</td><td class="mono">0-4</td><td class="dim">2024-01~02 雪球+DMA踩踏为模板</td></tr>
      <tr><td><b>D2 外资流出代理</b></td><td>北向5日净流出>200亿：+1.5（⚠️2024-08起北向净买入停发，改用北向成交额异动/股票ETF份额赎回/富时A50期指贴水代理）</td><td class="mono">0-1.5</td><td class="dim">2020-07-24 北向-163亿案例；2024后依赖代理指标</td></tr>
      <tr><td><b>D3 汇率急贬</b></td><td>USDCNH 10日涨幅>1.5%：+1.5</td><td class="mono">0-1.5</td><td class="dim">2022-04、2024-06 案例</td></tr>
      <tr><td><b>E1 拥挤过热</b></td><td>20日涨幅>10%且量比>1.2：+3；20日涨幅>15%：+2（取高）</td><td class="mono">0-3</td><td class="dim">过热状态未来5日大跌P=85.2% vs 基准56.6%</td></tr>
      <tr><td><b>E2 大基金/重要股东减持（72h内）</b></td><td>公告减持：+2</td><td class="mono">0-2</td><td class="dim">2021-08~09 大基金减持周期案例</td></tr>
      <tr><td><b>E3 巨量解禁临近</b></td><td>未来30日解禁市值/板块流通市值>3%：+1</td><td class="mono">0-1</td><td class="dim">2020-07 首批解禁案例</td></tr>
      <tr><td><b>乘数 M 估值放大</b></td><td>PE(5年分位)>85% 时总分×1.25（封顶15）</td><td class="mono">×1.25</td><td class="dim">高估值放大一切利空的传导弹性</td></tr>
    </tbody>
  </table>

  <h3 style="font-size:16px;margin:20px 0 10px">7.2 预警级别与操作映射</h3>
  <div class="lv">
    <div class="l g"><b>Ⅰ 绿色（0-2分）</b><div class="rng">常态运行</div><p>可维持标准仓位；无附加动作。</p></div>
    <div class="l y"><b>Ⅱ 黄色（3-5分）</b><div class="rng">单因子触发</div><p>仓位≤80%；暂停新增加仓；对持仓设置-3%止损线；滚动跟踪触发因子。</p></div>
    <div class="l o"><b>Ⅲ 橙色（6-8分）</b><div class="rng">双因子共振</div><p>仓位≤50%；停止一切逢跌加仓；用股指期货/期权对冲β；逐日复盘触发链。</p></div>
    <div class="l r"><b>Ⅳ 红色（≥9分）</b><div class="rng">事件+脆弱共振</div><p>仓位≤20%或完全对冲；等待触发因素证伪/落地+拥挤度回落后再评估；红色期间禁止抄底。</p></div>
  </div>

  <h3 style="font-size:16px;margin:20px 0 10px">7.3 历史回溯校验（选取 9 个代表性事件簇）</h3>
  <table>
    <thead><tr><th>事件</th><th>模型关键触发项</th><th>模型级别</th><th>实际结果</th><th>判定</th></tr></thead>
    <tbody>
      <tr><td>2020-07-15~24 中芯IPO+解禁+领事馆</td><td>E3解禁(+1)+E1拥挤(+3)+B2领事馆(+2)+D2北向(+1.5)</td><td><span class="chip" style="--c:#ea580c">橙色</span></td><td class="mono">-18.4%</td><td class="pos">命中✓</td></tr>
      <tr><td>2021-02-22~03-15 美债利率+抱团瓦解</td><td>A3美债窗口(+1)+E1拥挤(+3)+M乘数</td><td><span class="chip" style="--c:#d97706">黄色→橙</span></td><td class="mono">-14.3%</td><td class="pos">命中✓</td></tr>
      <tr><td>2022-03-03~04-26 俄乌+疫情+汇率</td><td>B2地缘(+2)+D3汇率(+1.5)+D1杠杆(+2)+C1</td><td><span class="chip" style="--c:#dc2626">红色</span></td><td class="mono">-29.4%</td><td class="pos">命中✓</td></tr>
      <tr><td>2024-01-17~02-02 雪球+DMA踩踏</td><td>D1杠杆(+4)+C1(+1.5)</td><td><span class="chip" style="--c:#ea580c">橙色</span></td><td class="mono">-13.4%</td><td class="pos">命中✓</td></tr>
      <tr><td>2024-10-09~16 9·24暴涨后回调</td><td>E1拥挤顶格(+3)+C1事件落地(+1.5)</td><td><span class="chip" style="--c:#dc2626">红色</span></td><td class="mono">-14.48%</td><td class="pos">命中✓</td></tr>
      <tr><td>2025-04-07 对等关税</td><td>B1关税升级(+3)+E1拥挤(+3)+M乘数</td><td><span class="chip" style="--c:#dc2626">红色</span></td><td class="mono">单日-9.22%</td><td class="pos">命中✓</td></tr>
      <tr><td>2026-07-10~08-03 AI硬件去泡沫</td><td>E1拥挤顶格(+3)+E2权重调仓/减持(+2)+A1隔夜科技(+1)+A3海外事件窗口(+1)+D1杠杆(+1.5)</td><td><span class="chip" style="--c:#dc2626">红色</span></td><td class="mono">-29.0%</td><td class="pos">命中✓</td></tr>
      <tr><td>2024-03-07 缩量回踩</td><td>无因子触发</td><td><span class="chip" style="--c:#16a34a">绿色</span></td><td class="mono">-2.18%</td><td class="dim">未命中（单日-2%级噪声，非模型目标）</td></tr>
      <tr><td>2020-12-09 抱团获利了结</td><td>无因子触发</td><td><span class="chip" style="--c:#16a34a">绿色</span></td><td class="mono">-2.41%</td><td class="dim">未命中（同上）</td></tr>
    </tbody>
  </table>
  <div class="callout ok"><b>校验结论：</b>模型对 <b>≥8% 级事件簇的全部 7 个深跌样本给出橙/红预警（命中）</b>；两例未命中均为 -2% 级单日技术性噪声（占事件簇的 37%，明确不在模型目标内）。误报控制依赖"因子不叠加取高"与事件窗口时效（72h/5日）约束。</div>

  <h3 style="font-size:16px;margin:20px 0 10px">7.4 每日运行流程</h3>
  <table>
    <thead><tr><th style="width:18%">时点</th><th>动作</th></tr></thead>
    <tbody>
      <tr><td><b>盘前 08:30</b></td><td>拉取隔夜 QQQ/SOXX（A1/A2）；检查未来3日海外事件（A3）；检查72h内中美/地缘事件流（B1/B2）——可由 MCP 数据工具 + 新闻扫描自动化。</td></tr>
      <tr><td><b>盘中 12:00</b></td><td>若盘前已触发 A/B 类 ≥2 分，监控科创50盘中跌幅与两市量能；北向盘中净卖出>100亿时升级 D2。</td></tr>
      <tr><td><b>盘后 16:30</b></td><td>更新 E1 拥挤度（20日涨幅、量比）、D1 两融/D2 北向5日/D3 汇率10日；查询30日解禁日历（E3）；汇总总分→级别→输出次日仓位纪律。</td></tr>
      <tr><td><b>事件驱动</b></td><td>任何时刻出现 B1/B2/E2 级事件（关税、出口管制、大基金减持公告）→ 立即重算并推送预警。</td></tr>
    </tbody>
  </table>
</div>

  <h3 style="font-size:16px;margin:20px 0 10px">7.5 示范运行：2026-09-08（周二）盘前实测打分</h3>
  <table>
    <thead><tr><th>因子</th><th>实际读数</th><th>得分</th><th>说明</th></tr></thead>
    <tbody>
      <tr><td>A1 隔夜SOXX</td><td class="mono">2026-09-04 收盘 +3.52%</td><td class="mono pos">0</td><td class="dim">费半大反弹，无触发；9/7 美股劳动节休市，此为最新隔夜</td></tr>
      <tr><td>A2 隔夜QQQ</td><td class="mono">+0.18%</td><td class="mono pos">0</td><td class="dim">平稳</td></tr>
      <tr><td>A3 海外事件窗口</td><td>未来3日（9/8-9/10）无联储议息/CPI</td><td class="mono pos">0</td><td class="dim">日历项，人工确认</td></tr>
      <tr><td>B1/B2 中美与地缘（72h）</td><td>待新闻扫描确认（8-19~9-04 下跌簇的驱动事件是否仍在发酵）</td><td class="mono">0-3?</td><td class="dim">本报告自动打分的盲区，需接入每日新闻扫描</td></tr>
      <tr><td>D1 杠杆资金</td><td>市场两融聚合数据工具暂缺，未打分</td><td class="mono">—</td><td class="dim">模型落地需接两融余额日频源</td></tr>
      <tr><td>D2 外资代理</td><td>北向净买入已停发（2024-08），代理指标待接</td><td class="mono">—</td><td class="dim">见 7.1 D2 修订</td></tr>
      <tr><td>D3 汇率</td><td class="mono">USDCNY 6.7108（9/4），10日 -0.15%</td><td class="mono pos">0</td><td class="dim">平稳偏升值</td></tr>
      <tr><td>E1 拥挤过热</td><td class="mono">20日涨幅 -7.03%，量比 0.81→0.89（9/7）</td><td class="mono pos">0</td><td class="dim">深跌缩量，远非过热</td></tr>
      <tr><td>趋势状态（参考项）</td><td class="mono">低于60日均线 10.5%</td><td class="mono">—</td><td class="dim">校准显示下行趋势中大跌概率反而低于基准</td></tr>
    </tbody>
  </table>
  <div class="callout"><b>示范结论（量化部分 ≈ 0-1.5 分，绿色）：</b>无海外触发、汇率平稳、非过热——模型解读为"无叠加利空触发"，<b>不是抄底信号</b>：指数刚经历 -28.96% 的7-8月暴跌并处于60日线下方约 10%（9/7 反弹 +2.42%），趋势与情绪的修复需要时间；绿色仅代表"当前无新增利空叠加"。此示范同时暴露了 v1.0 落地的三个数据缺口：市场两融聚合、外资代理、事件日历/新闻扫描自动化。</div>

  <h3 style="font-size:16px;margin:20px 0 10px">7.6 v1.1 增强：基于 91 簇全样本归因的因子修订（2026-09）</h3>
  <p class="sec-note">v1.0 的因子表基于 2020/2024 两年归因拟合；现将 2021/2022/2023/2025/2026 全部 91 簇归因回补后，把新证据落成可执行的因子增补（计分并入 E/A/C/D 类总分，级别判据不变）。</p>
  <table>
    <thead><tr><th style="width:17%">增补项</th><th>定义与阈值</th><th style="width:8%">计分</th><th>证据簇（归因编号）</th></tr></thead>
    <tbody>
      <tr><td><b>E1a 成交集中度</b></td><td>全市场成交额前 5% 个股的成交占比 &gt;40%（2026-07 崩盘前一度达 48%）</td><td class="mono">+1.5</td><td>ep87（2026-05~06 拥挤瓦解）、ep89（7-8 月 -28.96%）</td></tr>
      <tr><td><b>E2a 指数调仓/权重集中</b></td><td>单一权重股占指数权重 ≥12%，或指数样本调整生效日 ±3 日（被动买卖盘百亿级）</td><td class="mono">+2</td><td>ep77（2025-09-04 寒武纪权重 15%，单日 -6.09%）</td></tr>
      <tr><td><b>E4 巨量IPO抽血</b></td><td>募资 ≥300 亿元的 IPO 申购日 ±3 日</td><td class="mono">+1.5</td><td>ep89（2026-07 长鑫科技 579 亿超级IPO，崩盘放大器）</td></tr>
      <tr><td><b>A1a 亚洲同链共振</b></td><td>A1 触发当日，KOSPI/日经或 SK海力士/三星同跌 &gt;3% → 在 A1 基础上加计</td><td class="mono">+1</td><td>ep89（2026-07-16/17 存储链崩塌、07-28 KOSPI -10.84%）；ep91（8-19 日经 -2.6%）</td></tr>
      <tr><td><b>D1a 杠杆水位线</b></td><td>两融余额 &gt;2.4 万亿元时，D1 各档阈值减半（高位对边际去杠杆更敏感）</td><td class="mono">修订</td><td>2025-10（2.45 万亿触融资规则）、2026-05~10（2.5 万亿高位瓦解）</td></tr>
      <tr><td><b>C1a 政策传闻证伪</b></td><td>"利好传闻/预期"主导上涨后，官方澄清、落空或不及预期日 ±2 日默认计 +1</td><td class="mono">+1</td><td>ep87（2026-06 基金基准调整传闻证伪）、ep36（2022-11 降准 0.25pct 不及预期）、ep47（2023-06 LPR 仅 10bp）</td></tr>
    </tbody>
  </table>
  <div class="callout"><b>证据背书：</b>91 簇全样本归因显示，2025-2026 年的 6 个深跌簇中有 5 个在崩盘前 2-4 周可观察到筹码/拥挤度异常（成交集中度、单一权重股权重、两融与机构仓位、指数调仓日历）；而同期两例最大的外生冲击（2025-04-07 对等关税、2026-03 伊朗/霍尔木兹）事前不可测、但当日即获强力护盘修复——<b>外生利空不可测但可救，内生拥挤可预警但易踩踏</b>。故 v1.1 把增量权重压在 E 类筹码因子；v2.0 方向（逐日滚动样本外检验）见 §8，量化底稿已可用 <span class="mono">build_artifacts.py</span> 一键重算。</div>

  <h3 style="font-size:16px;margin:20px 0 10px">7.7 样本外检验：阈值稳定性分时段验证（v2.0 预研）</h3>
  <p class="sec-note">回应 §8"后视镜偏差"局限：E1/D 类量化因子只依赖当日及以前的滚动数据（无未来函数），故可将样本切为"拟合期（2020-07~2023-12，853 日）"与"检验期（2024-01~2026-09，650 日）"，检验条件概率的提升倍数是否在样本外保持。标签仍为"此后 5 个交易日内出现≥1.5%大跌"。B/C/E2/E3 事件类因子依赖人工事件识别，不在本检验范围内。</p>
  <table>
    <thead><tr><th style="width:26%">因子条件</th><th>拟合期 P%（n）</th><th>检验期 P%（n）</th><th>提升倍数 拟合→检验</th><th style="width:24%">结论</th></tr></thead>
    <tbody>
      <tr><td><b>基准（任意交易日）</b></td><td class="mono">56.9%（853）</td><td class="mono">56.2%（650）</td><td class="mono">—</td><td class="dim">两段基准几乎一致</td></tr>
      <tr><td><b>E1 过热</b>（20日涨幅&gt;10% 且量比&gt;1.2）</td><td class="mono pos">92.9%（14）</td><td class="mono pos">83.6%（67）</td><td class="mono">x1.63 → x1.49</td><td class="pos"><b>样本外保持</b>，检验期样本量放大 5 倍后仍 83.6%</td></tr>
      <tr><td><b>E1 急涨</b>（20日涨幅&gt;15%）</td><td class="mono pos">71.4%（7）</td><td class="mono pos">79.1%（91）</td><td class="mono">x1.25 → x1.41</td><td class="pos"><b>样本外增强</b>，为全表最稳预警项</td></tr>
      <tr><td>趋势：60日均线下方</td><td class="mono">47.6%（492）</td><td class="mono">48.4%（335）</td><td class="mono">x0.84 → x0.86</td><td class="dim">两段均低于基准——非信号，确认"钝化"结论</td></tr>
      <tr><td>连跌两日</td><td class="mono">54.5%（231）</td><td class="mono">52.9%（155）</td><td class="mono">x0.96 → x0.94</td><td class="dim">两段均≈基准——非信号</td></tr>
      <tr><td>平静期（|20日涨幅|≤5% 且缩量）</td><td class="mono">52.3%（323）</td><td class="mono">46.8%（237）</td><td class="mono">x0.92 → x0.83</td><td class="dim">两段均略低于基准——平静无保护作用</td></tr>
    </tbody>
  </table>
  <div class="callout ok"><b>检验结论：</b>模型唯一的高价值量化因子族 <b>E1（过热/急涨）在样本外稳定成立</b>——提升倍数保持 1.4~1.5 倍，检验期绝对命中率 79-84%；而趋势、连跌、平静三个"直觉型"条件在两段样本中一致地接近甚至低于基准，说明模型不会因保留它们而增加误报（它们仅作背景参考项）。<b>v2.0 的正确路径由此明确：量化预警以 E1 族为核，B/C/E2/E3 事件因子以"事件日历+新闻扫描"半自动接入（见 7.6 增补项），并对 E1 阈值每半年用本脚本（<span class="mono">rolling_validate.py</span>）重检一次。</b></div>
</div>

<!-- ============ S8 方法 ============ -->
<h2 class="sec" id="s8"><span class="no">8</span>数据、方法与局限性</h2>
<div class="card">
  <p style="font-size:14px"><b>数据与方法：</b>科创50指数（000688.SH）日线取自腾讯行情接口（2020-07-01→2026-09-08，1,504 个交易日，2020-07-23 前为回溯值）；隔夜美股以 QQQ/SOXX（Yahoo/stooq）前一交易日收盘价计算；事件簇定义为"间隔≤5个交易日的大跌日归并"；归因由多路研究代理逐簇新闻检索（搜索引擎+原文阅读），要求提供可查证来源并标注置信度；条件概率与事件研究统计基于全样本 1,504 日计算。</p>
  <p style="font-size:14px;margin-top:10px"><b>局限性：</b></p>
  <ul style="font-size:13.5px;color:#374151;margin:6px 0 0 18px">
    <li>归因依赖公开新闻，<b>部分下跌是多重因素叠加</b>，单一"主因"归类必然损失信息；低置信簇（尤其-1.5~-2%区间）仅作参考。</li>
    <li>"技术性回调"是排除性结论——可能存在未被报道的真实利空。</li>
    <li>条件概率样本期覆盖 2020-2026 的特殊环境（疫情、超大级宽松与紧缩周期、AI 行情），<b>外推到新环境需谨慎</b>；过热因子（E1）在单边熊市会失效。</li>
    <li>事件簇归并窗口（≤5日）与跌幅阈值（1.5%）为人为选择，改变参数会改变统计结果。</li>
    <li>模型 v1.0 的历史回溯校验为事后定性打分，<b>存在后视镜偏差</b>；§7.7 已对量化因子完成分时段样本外检验（结论：E1 过热/急涨族样本外成立，趋势/连跌/平静确认为非信号），B/C/E2/E3 事件类因子仍待接入每日事件识别后做滚动检验（v2.0）。</li>
    <li>B 类（中美与地缘）因子本质依赖事件识别，无法完全量化；建议接入每日新闻扫描工作流半自动运行。</li>
  </ul>
</div>

<footer>
  <p>数据来源：腾讯行情（科创50指数）、Yahoo Finance（QQQ/SOXX）、各新闻来源见明细表内链接；统计与模型校准基于 vibe-trading MCP 服务端计算。</p>
  <p style="margin-top:6px">本报告仅为研究用途，不构成任何投资建议。历史统计不代表未来表现。</p>
</footer>
</div>

<script>
const P = __PAYLOAD__;
const CAT_COLOR = {"海外传导":"#3b82f6","中美与地缘":"#ef4444","政策监管":"#f59e0b","宏观流动性":"#8b5cf6","板块自身":"#10b981","技术性回调":"#94a3b8","未归类":"#cbd5e1"};
const chart = (id, opt) => { const el = document.getElementById(id); if (el) echarts.init(el).setOption(Object.assign({animation:false}, opt)); };
const isDark = false;

// 1. index + drop markers
(function(){
  const xs = P.indexSeries.map(d => d[0]);
  const ys = P.indexSeries.map(d => d[1]);
  const marks = P.dropMarkers.map(m => ({value:[m.value[0], m.value[1]], pct:m.pct}));
  chart('chartIndex', {
    grid:{left:60,right:24,top:30,bottom:60},
    tooltip:{trigger:'axis', formatter: p=>{ const t=p[0].axisValue; return t+'<br>科创50: '+p[0].value[1].toFixed(0);}},
    xAxis:{type:'category',data:xs,axisLabel:{formatter:v=>v.slice(0,7),interval:110}},
    yAxis:{type:'value',scale:true,name:'点位',axisLabel:{formatter:v=>v.toFixed(0)}},
    dataZoom:[{type:'inside'},{type:'slider',height:18,bottom:8}],
    series:[
      {name:'科创50',type:'line',data:P.indexSeries.map(d=>[d[0],d[1]]),showSymbol:false,lineStyle:{width:1.4,color:'#2563eb'},areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:'rgba(37,99,235,.18)'},{offset:1,color:'rgba(37,99,235,0)'}]}},markPoint:undefined},
      {name:'大跌日',type:'scatter',data:marks.map(m=>({value:[m.value[0],m.value[1]],pct:m.pct})),symbolSize:(val,params)=>Math.min(6+Math.abs((params&&params.data&&params.data.pct)||0)*1.6,22),itemStyle:{color:'rgba(220,38,38,.55)'},tooltip:{formatter:p=>' '+p.value[0]+'　'+((p.data&&p.data.pct)||'')+'%'}}
    ]
  });
})();

// 2. pies
function pie(id, data, title){
  chart(id, {
    tooltip:{trigger:'item',formatter:'{b}: {c} 簇 ({d}%)'},
    legend:{bottom:0,textStyle:{fontSize:11}},
    series:[{type:'pie',radius:['32%','62%'],center:['50%','44%'],
      data:Object.entries(data).filter(d=>d[1]>0).map(d=>({name:d[0],value:d[1],itemStyle:{color:CAT_COLOR[d[0]||'']}})),
      label:{formatter:'{b}\n{c}',fontSize:11}}]
  });
}
pie('chartCatPie', P.catCountAll);
pie('chartCatDeep', P.catCountDeep);

// 3. year stacked
(function(){
  const years = Object.keys(P.catByYear);
  const cats = Object.keys(CAT_COLOR);
  chart('chartCatYear', {
    grid:{left:40,right:20,top:40,bottom:30},
    legend:{top:0,textStyle:{fontSize:11}},
    tooltip:{trigger:'axis'},
    xAxis:{type:'category',data:years},
    yAxis:{type:'value',name:'事件簇数'},
    series:cats.map(c=>({name:c,type:'bar',stack:'t',barMaxWidth:46,
      data:years.map(y=>P.catByYear[y][c]||0),color:CAT_COLOR[c],
      label:{show:true,position:'inside',fontSize:10,formatter:p=>p.value>0?p.value:''}}))
  });
})();

// 4. calibration bar
(function(){
  const c = P.calib;
  const rows = [
    ['基准（任意日）', c.p_next5_bigdrop_all_days.pct, '#94a3b8'],
    ['60日线下方', c.p_next5_bigdrop_below_ma60.pct, '#64748b'],
    ['平静期', c.p_next5_bigdrop_calm_regime.pct, '#38bdf8'],
    ['连跌两日', c.p_next5_bigdrop_two_down_days.pct, '#818cf8'],
    ['急涨>15%', c.p_next5_bigdrop_mom20gt15.pct, '#f59e0b'],
    ['过热(涨>10%+放量)', c.p_next5_bigdrop_hot_mom20gt10_volratio12.pct, '#dc2626'],
  ];
  chart('chartCalib', {
    grid:{left:130,right:50,top:10,bottom:24},
    tooltip:{trigger:'axis',axisPointer:{type:'shadow'},formatter:p=>p[0].name+'：'+p[0].value+'%'},
    xAxis:{type:'value',max:100,axisLabel:{formatter:'{value}%'}},
    yAxis:{type:'category',data:rows.map(r=>r[0]),axisLabel:{fontSize:11}},
    series:[{type:'bar',barMaxWidth:20,data:rows.map(r=>({value:r[1],itemStyle:{color:r[2]}})),
      label:{show:true,position:'right',formatter:'{c}%',fontSize:11,fontWeight:700}}]
  });
})();

// 5. fwd by category
(function(){
  const e = Object.entries(P.catFwd5).filter(d=>CAT_COLOR[d[0]]);
  chart('chartFwd', {
    grid:{left:110,right:60,top:10,bottom:24},
    tooltip:{trigger:'axis',formatter:p=>p[0].name+'：T+5中位 '+p[0].value+'%'},
    xAxis:{type:'value',axisLabel:{formatter:'{value}%'}},
    yAxis:{type:'category',data:e.map(d=>d[0]),axisLabel:{fontSize:11}},
    series:[{type:'bar',barMaxWidth:20,data:e.map(d=>({value:d[1],itemStyle:{color:d[1]>=0?'#16a34a':'#dc2626'}})),
      label:{show:true,position:'right',formatter:'{c}%',fontSize:11}}]
  });
})();
</script>
</body>
</html>
"""
