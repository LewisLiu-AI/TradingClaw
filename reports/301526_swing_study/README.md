# 301526 国际复材 — 波段策略研究

> **策略已冻结为可复用模块**：[STRATEGY.md](STRATEGY.md)（规格书）+ `swing_strategy.py`（含四档预设与 CLI）。
> ⚠️ **第 14 节是勘误**，修正了两个实现缺陷并覆盖第 11、13 节的部分数字。
> 数据采集与验证经验已固化为 skill：`ashare-data-lab`。

**结论请看 [REPORT.md](REPORT.md)**（数据清单 / 波段真值 / 信号研究 / 策略设计 / 回测 / 跨标的稳健性 / 风险提示）。

## 一句话结论

**宏观层面找不到可靠区分"适合/不适合交易月份"的方法**（详见 REPORT.md 第 11 节）：
市场变量对"先手层是否有效"的解释力 |Spearman| ≤ 0.23；波动率假设被否证（p=0.226）；
真正有效的过滤是信号级的（砍掉 B3 死代码、先手层只留 B1+B2），交易数可降 71% 而指标不降。

**可迁移性（20 只同类标的）**：这套规则在 301526 上是**定制的** —— 捕获率（策略/买入持有）1.23，
但搬到其他 19 只上捕获率中位仅 **0.36**。可迁移的只有两个简单组件：①"削回撤"（18~19/20 只改善，
中位 -45.9%→-30.1%，代价是收益）；②"满仓+25%追踪止损"（捕获率中位 1.03、收益改善 13/20）。
波动率归一化（ATR 自适应）不解决问题。详见 REPORT.md 第 12 节。

顶部可预测（召回 93%）、底部难预测（只有"恐慌型"急跌有效）；但按顶部信号减仓会显著牺牲收益。
真正有效的是**趋势滞回带**（容忍跌破 MA20 5% 才离场）：全样本 822.8% / 回撤 -28.9%（纯核心），
叠加抄底先手后 966.5% / -32.4%，对比买入持有 670.1% / -50.8%。
**跨 9 只同类标的检验：削回撤能泛化（7~9/9），提收益不能泛化（1/9）**。

## 文件

| 文件 | 作用 |
|---|---|
| `REPORT.md` | 完整研究报告（结论、数据、策略、回测、风险、局限） |
| `fetch_data.py` | 数据抓取（行情/融资融券/资金流/大宗/龙虎榜/股东户数/解禁/公告/指数） |
| `swing_lib.py` | 核心库：数据汇聚、因果特征、ZigZag 真值、A 股回测引擎、指标 |
| `strategy.py` | 子策略（A/B1/B2/B3/C/D）与组合状态机 |
| `signal_engine.py` | **自包含策略引擎**（仓库回测框架可直接调用），含 `SignalEngine` 入口 |
| `run_swing.py` | CLI：打印最新信号、写 `latest_signal.json` |
| `explore_signals.py` | 波段真值 + 特征 AUC 研究（样本内/样本外分开） |
| `layers.py` | 逐层拆解：确认哪一层真的加价值 |
| `tune_trend.py` | 滞回带网格 + 层叠加 + 均线对选择 |
| `walkforward.py` | 分窗口/检测命中率/分段稳健性/参数敏感性 |
| `cross_check.py` | 跨 9 只标的稳健性（缓存到 `data/peers/`） |
| `cross_variants.py` | 跨标的结构变体对比（风险/收益边界） |
| `final_check.py` | 置换检验 + 交易明细 + 终检 |
| `fetch_macro.py` | 抓市场级数据（宽基指数、沪深两融余额） |
| `analyze_macro.py` | 股票-月面板：市场状态能否预判"先手层有效" |
| `macro_gate_test.py` | gate 的 bootstrap 显著性检验 + 样本内外一致性 |
| `macro_gate_final.py` | 各 gate 配置终检 + 逐月日历 + 跨 9 只标的 |
| `filter_test.py` | 信号级过滤（砍 B3 / 只留 B1+B2）vs 月份级过滤 |
| `portability.py` | 可迁移性检验（20 只标的）：这套规则能否用于别的股票 |
| **`STRATEGY.md`** | **策略冻结规格书**：规则、四档预设、适用性体检、三条"不要做" |
| **`swing_strategy.py`** | **股票无关的可复用策略模块**（含回测/体检/信号 CLI） |
| `rerun_filters.py` | 第 14 节勘误：用正确实现重算全部"筛选/gate"结论 |
| `macro_global.py` | 跨资产/海外因子（黄金/原油/美债/VIX/费半/纳指/铜/恒生）能否区分月份 |
| `macro_global_gate.py` | 海外因子 gate 的实盘效果 |
| `macro_global_combo.py` | 海外+本土信息叠加在精简之上的组合对比 |
| `run/` | 仓库回测框架入口（`config.json` + `code/signal_engine.py`，已过 AST 与契约校验） |
| `data/` | 全部原始数据 CSV（含 `_manifest.json`） |
| `results_*.csv/json` | 回测结果产物 |


## 环境对照（开发 / 生产）

| | 开发机（macOS） | 生产服务器（47.100.42.183） |
|---|---|---|
| 本目录 | `/Users/lewis/code/TradingClaw/reports/301526_swing_study` | `/opt/vibe-trading/reports/301526_swing_study` |
| Python | `.venv/bin/python` (3.12) | `/opt/vibe-trading/venv/bin/python`（或 `python3.11`） |
| skill | `~/.codex/skills/ashare-data-lab`（软链到 `~/.zcode/skills/`） | `/opt/vibe-trading/agent/src/skills/ashare-data-lab` + `/root/.zcode/skills/ashare-data-lab` |

⚠️ 生产系统的 `python3` 是 **3.6.8**，本目录脚本用了 3.7+ 语法（`from __future__ import annotations`），
**必须用 venv 或 python3.11**。

`scripts/deploy.sh` 的 rsync **排除了 `reports/`**，所以本目录要用单独的 rsync 同步（见下方"部署"）。

## 快速使用

```bash
python fetch_data.py                       # 更新数据
python run_swing.py                        # 当前建议仓位
python walkforward.py                      # 完整走查
```

## 当前信号（数据截至 2026-09-11）

建议仓位 **0%**：收盘 30.69 站上 MA20 仅 +0.9%，MA20 < MA60（趋势未修复）。
**注意 2026-12-28 解禁 23.66 亿股（占总股本 62.8%、占流通市值 168.5%）**。

> 本研究为量化回测与分析，不构成投资建议。样本仅 556 个交易日、单标的，结论置信区间很宽，请阅读 REPORT.md 第 10 节的局限清单。
