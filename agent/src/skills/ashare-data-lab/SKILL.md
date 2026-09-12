---
name: ashare-data-lab
description: "A股研究数据采集与数据验证：抓行情/融资融券/资金流/大宗/龙虎榜/公告/指数/跨资产/北向成交额，并在跑回测前做结构与口径校验。触发词：抓A股数据/拉数据/取行情/融资融券数据/资金流向/北向/宏观数据/数据校验/检查数据/数据有坑/口径不对/单位不对/回测数据准备。"
---

# A股数据采集与验证

**这套流程的价值在于避免静默错误。** 本 skill 的每条规则都对应一次真实踩坑（名单见
[references/pitfalls.md](references/pitfalls.md)，共 14 条）——它们的共同特征是**不报错、只出错**：
抓到的数据看起来完全正常，回测照样跑出结果，但数字是错的。

**铁律：任何回测/统计之前，先跑一遍校验器。** 采集完立刻跑，不要等结果反常再回头查。

脚本目录（本 skill 自带，取存在者）：
- 开发机：`~/.codex/skills/ashare-data-lab/scripts/`（或 `~/.zcode/skills/ashare-data-lab/`）
- 生产：`/opt/vibe-trading/agent/src/skills/ashare-data-lab/scripts/`

下称 `$SK`。**解释器**：生产用 `/opt/vibe-trading/venv/bin/python`（已含 pandas/numpy/requests），
或 `python3.11`；**不要用系统的 python3（3.6.8）** —— 脚本用了 3.7+ 语法。

**完整范例**（17 个数据 CSV + 研究报告 + 可复用策略模块 `swing_strategy.py`，可直接照抄结构）：
- 开发机：`/Users/lewis/code/TradingClaw/reports/301526_swing_study/`
- 生产：`/opt/vibe-trading/reports/301526_swing_study/`

## 任务 A：采集数据

```bash
# 开发机用 python；生产用 /opt/vibe-trading/venv/bin/python
python "$SK/scripts/fetch_ashare.py" --symbol 301526.SZ --outdir ./data \
    --start 2024-06-01 --end 2026-09-12
# 可选步骤: prices,index,margin,market_margin,block,ann,global,northbound
# 只跑某几步: --only prices,margin ；跨资产: --global-macro ；北向: --northbound
```

产出：`px_raw/px_qfq/px_hfq.csv`（三口径）、`idx_*.csv`（创业板指/沪深300/中证500/上证50/两市指数）、
`margin.csv`（个股两融，657 天全历史）、`mkt_margin.csv`（市场级两融，**分析用 `mkt_rz_balance_sh`**）、
`block_trade.csv`、`announcements.csv`、`global/*.csv`、`northbound_turnover.csv`。

**东财 push2his 经本地代理会间歇性 ProxyError** —— 脚本已内置重试 + 新浪兜底，但兜底源的换手率是
**小数口径**（0.0433 = 4.33%）。脚本按量级自动归一为百分数；**不要自己硬编码 `*100`**。

## 任务 B：验证数据（强制）

```bash
python "$SK/scripts/validate_data.py" ./data --market px_qfq.csv --expected-last 2026-09-12
```

7 类检查：`C1` OHLC 结构 / `C2` 日期（重复、周末、缺口、日历错位）/ `C3` 覆盖率（含**最大连续缺口**）/
`C4` 单位量级 / `C5` 新鲜度 / `C6` 复权自洽 / `C7` 跨源自洽。退出码 1 = 有 ERROR，**先修再分析**。

已知良好数据集上的基线是 **0 ERROR / ≤10 WARN**；WARN 突然变多通常意味着数据源改了口径。

## 任务 C：陷阱速查（完整版见 references/pitfalls.md）

| 症状 | 原因 | 处置 |
|---|---|---|
| 换手率全部 ~0.04 | 小数口径（新浪） | 按量级归一，勿硬编码 ×100 |
| 某市场级序列大段"无变化" | 单侧数据缺口被 ffill 成常数 | 换完整腿（沪市单边），勿用 ffill 掩盖 |
| 两融/成交额量级差 1e4/1e8 | 元 / 万元 / 亿元 混用 | 校验器 C4；分析前统一为亿元 |
| 北向净买入返回空 | **2024-08-19 起停止披露** | 只能用成交额（HKEX 官方），见 data-sources |
| 文本列(席位)变成 NaN | 对整表做 `to_numeric` | 只对数值列转换 |
| 拼接后出现整段 NaN | `concat` 按索引并集对齐 | 先 `reindex` 到主表索引 |
| 回测满仓买不进 | 初始资金太小 / 成本挤占现金 | 初始资金给足（如 100 万）；按可用现金折算股数 |
| 结果好得不真实 | 前视偏差：用了当日收盘后才知道的数据 | 晚间披露类(两融/龙虎榜/大宗)统一 `shift(1)` |
| 止损永不触发 / 天天触发 | 带宽符号写反 | 离场是 `MA20×(1-sell_band)`；用已知结果做回归校验 |

## 任务 D：先查可得性，再设计因子

**动手写因子之前先确认数据是否存在**，否则会白花时间在一个拿不到的变量上。
可得性矩阵（单位、披露滞后、停更日期）见 [references/data-sources.md](references/data-sources.md)。

三条最容易踩的"数据已不存在"：

- **北向资金净买入**：2024-08-19 起停止披露；现存只有 HKEX 的**成交额**（北向连买卖拆分都没有，南向才有）。
- **全市场涨跌家数 / 涨停家数**：只有当日快照，无历史序列。
- **深市两融的 akshare 口径**：2024-06~2025-06 系统性缺 177 个交易日（用沪市单边替代）。

## 任务 E：把数据变成可复现的研究

1. **落盘到 `data/`，英文列名 + `date` 索引**，配 `_manifest.json`（采集器自动生成）。
2. **写成独立脚本**，不要只在交互里算：`fetch_*.py` → 校验 → 分析脚本。
3. **特征只用 T 日及之前的信息**，并在代码注释里写明滞后约定。
4. **留一条回归校验**：已知输入 → 已知输出（例：某预设应得 966.47%）。改动后先跑它。
5. **收益/风险指标同时看均值与中位数** —— n 小时中位数会跳（本研究 9 只标的上出现过
   "6/9 改善但中位数下降"）。
6. **交叉验证两份独立实现**：同一规则写成两条路径，用"全集合"配置对齐。本研究正是靠这一步
   才发现旧脚本"过滤轨迹 vs 重跑状态机"的方法学缺陷与一个符号错误。
