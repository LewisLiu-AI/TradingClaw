---
name: star50-warning
description: "科创50利空预警模型：盘前打分、收盘数据更新、新大跌日归因、报告重建。触发词：科创50打分/盘前打分/预警级别/更新模型/今天大跌归因/重建报告/STAR50 warning score。"
---

# 科创50 利空预警模型 — 使用与更新

**工作目录（自动探测，取存在者）**：
- 生产：`/opt/vibe-trading/reports/star50_study`
- 开发：`/Users/lewis/code/TradingClaw/reports/star50_study`

下称 `$ST`。**完整手册**：`$ST/HANDOFF_归因数据搜集任务.md`（事件簇对照表、数据源路径、渲染校验坑）——本 skill 是其操作摘要。

模型现状：91 簇归因（2020-2026）、v1.1 因子集、双版本报告（HTML+PDF）、
交易日 08:30 已有 cron 自动打分（automationId `automation-f3dfaca2-e9f6-4c12-a990-e1b81c2014c6`）。

## 任务 A：盘前 / 任意时刻打分（最常用）

```bash
cd $ST
# 零参数（隔夜自动读 data/soxx.csv、data/qqq.csv，需为最新）：
python3 daily_score.py
# 或手工传入隔夜与汇率（%）：
python3 daily_score.py --soxx -1.2 --qqq -0.8 --fx10d 0.3
# 事件因子命中后加开关：--a3 --a1a --b1 --b2 --c1 --c2 --d1-lever --d2 --e1a --e2 --e3 --e4
# 历史复演：python3 daily_score.py --date 2026-07-01
```

输出总分 → 级别：Ⅰ绿 0-2（常态）/ Ⅱ黄 3-5（单因子）/ Ⅲ橙 6-8（共振）/ Ⅳ红 ≥9（事件+脆弱），
并给出仓位纪律。**绿色≠不会跌**（目标仅 ≥3% 单日与 ≥8% 簇）。

**事件扫描七步**（B1/B2/E2/C1/C2/A3/E3，命中传开关）——严格按 HANDOFF §0.6 清单执行，
工具调用语句已逐条实测写在那里（wind `get_financial_news`/`get_stock_events`、两融与 PE 分位用
wind `get_stock_fundamentals`、隔夜用 Yahoo chart API）。⚠️ vibe-trading MCP 会话易失效，换 wind/内置 WebSearch。

## 任务 B：收盘后数据更新（每交易日 15:10 后）

1. 取当日指数 OHLCV：`curl -s "https://qt.gtimg.cn/q=sh000688" | iconv -f GBK -t UTF-8`，
   按 `~` 分割：[30]时间戳、[5]开、[33]高、[34]低、[3]收、[6]量（已实测，勿改索引）。
2. 若日期新于 `$ST/star50_index.csv` 末行 → 追加一行，**并同步 `/tmp/star50_index.csv`**（build_report 优先读它）。
3. 重算底稿：`python3 build_artifacts.py`（干跑核对）→ `python3 build_artifacts.py --write`。

## 任务 C：出现新大跌日（单日 ≤-1.5%）

干跑会打印 `NEW episodes` 或"相对现有新增"。

- 若日期与既有簇末跌日间隔 ≤5 个交易日 → **扩展该簇**（改该条目的 dates/cum_drop/detail，不新增 id）。
- 若为新簇 → episode_id 从 **92** 递增，写入 `attribution_raw/{YYYY}.json`。
- 归因要求：六类目（信息量大的类放首位，可 "A | B"）、catalyst ≤20 字、detail ≤100 字写清"日期→事件"、
  sources 1-3 条真实 URL（金融垂搜 `finance_search` 用 date_from/to 卡窗口；被内容过滤拦截就换词重试；
  禁止编造来源）、confidence 高/中/低。找不出利空 → 如实归"技术性回调"+低置信。
- 深跌簇（≤-8% 或单日 ≤-4%）多花搜索预算；≥8% 级新簇考虑在 build_report.py CASES 追加案例卡
  并同步 template.py §7.3 校验表。

## 任务 D：重建报告

```bash
cd $ST && python3 build_report.py   # HTML；确定性构建
```

PDF 导出需要 Chromium：**开发机（macOS）**：

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
  --no-pdf-header-footer --virtual-time-budget=20000 \
  --print-to-pdf="$ST/科创50单日大跌利空归因与预警模型.pdf" "file://$ST/科创50单日大跌利空归因与预警模型.html"
```

生产 Linux 服务器默认无 Chrome——PDF 请在开发机导出后同步，或安装 chromium 后把路径替换。

模板硬编码统计（表头日期、大跌日个数、交易日数、分档天数）随数据更新需手工同步——
改前 `grep -n "259\|1,50[0-9]" template.py` 列出全部位置。

## 红线

- 不手改 HTML / artifacts；不改既有归因条目（只扩展或追加）。
- 分桶规则与隔夜条件概率已全量校验固化在 build_artifacts.py，勿改定义；改前先干跑验证 91 簇复现。
- 报告渲染校验要点（scrollbox 截断、分段截图、ECharts 尾脚本）见 HANDOFF §0.5。
