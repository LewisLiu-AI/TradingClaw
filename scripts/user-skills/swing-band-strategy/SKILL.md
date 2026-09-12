---
name: swing-band-strategy
description: 波段趋势策略（趋势滞回带 + 恐慌先手层）的使用：取当前目标仓位、回测复现、换标的的适用性体检、仓位与离场纪律、以及三条已验证会亏钱的禁忌。参考实现为 301526 国际复材研究（2026-09）。触发词：波段策略/趋势策略/复材策略/国际复材/301526/取信号/目标仓位/今天该买吗/该不该买/仓位多少/什么时候卖/回测这个策略/策略适用吗/能不能用到别的股票。
---

# 波段趋势策略 — 使用说明

**它输出「目标仓位」（0 / 0.7 / 1.0），不是买卖价。** T 日收盘生成 → **T+1 开盘成交**。

```
L1+L2 趋势滞回带（收益引擎，唯一稳健有效的层）
  空仓 → 满仓(1.0) : 收盘 > MA20×1.05  且  MA20 > MA60
  满仓 → 空仓      : 收盘 < MA20×0.95  或  MA20 下穿 MA60
  MA20 上下 5% 以内维持原状态        ← "5% 容忍带"是抗震荡的关键
L3 先手层（仅空仓时，0.7 仓试探）
  B1 系统性恐慌: 距20日高点<-13% 且 5日跌<-6% 且 创业板指5日<-1.5% 且 ATR%>4
  B2 个股崩跌  : 距20日高点<-35% 且 5日跌<-10% 且 RSI14<45
```

**它一年只动几次手**（2.3 年核心版仅 5 笔交易），目的是吃满整段趋势、避开腰斩。
不要拿它当短线信号源。

## 环境与路径

| | 开发机 | 生产 |
|---|---|---|
| 工作目录 | `~/code/TradingClaw/reports/301526_swing_study` | `/opt/vibe-trading/reports/301526_swing_study` |
| 解释器 | 仓库 `.venv/bin/python` | **`/opt/vibe-trading/venv/bin/python`**（系统 `python3` 是 3.6.8，跑不了） |
| 规格书 / 报告 | 同目录 `STRATEGY.md` / `REPORT.md` | 同目录 |

下称 `$ST`（取存在者）。**动手前先 `cd $ST`** —— 命令里的 `data/` 都相对于它。

## 任务 A：取当前仓位（最常用）

```bash
cd $ST
$PY swing_strategy.py --csv data/px_qfq.csv --market data/idx_cyb.csv --signal
```

输出 JSON，`target_position` 即答案。判断依据三件套（口径见下）：

```bash
# 看门槛数值（进场价 / 离场价 / 先手触发距离）
$PY - <<'EOF'
import pandas as pd, swing_strategy as sw
d = sw.attach_market(sw.build_features(pd.read_csv("data/px_qfq.csv", parse_dates=["date"]).set_index("date")),
                     pd.read_csv("data/idx_cyb.csv", parse_dates=["date"]).set_index("date")["close"])
ma20, ma60, c = d.ma20.iloc[-1], d.ma60.iloc[-1], d.close.iloc[-1]
print(f"截至 {d.index[-1].date()} 收盘 {c:.2f} | MA20 {ma20:.2f} MA60 {ma60:.2f}")
print(f" 进场: 收盘>{ma20*1.05:.2f} 且 MA20>MA60 (当前差 {ma60/ma20-1:+.1%})")
print(f" 离场: 收盘<{ma20*0.95:.2f}   | 先手: 距20日高点{d.dd_high20.iloc[-1]:+.1f}% / 5日{d.ret5.iloc[-1]:+.1f}% / 创业板5日{d.mkt_ret5.iloc[-1]:+.1f}% / ATR{d.atr_pct.iloc[-1]:.1f}")
EOF
```

**必须挂大盘序列**：缺 `mkt_ret5` 时 B1 的"大盘同步走弱"条件会被跳过，策略变成另一套
（同一标的 966%/33 笔 → 746%/42 笔）。模块会抛 `RuntimeWarning` —— 别忽略。

## 任务 B：回测与回归校验

```bash
$PY swing_strategy.py --csv data/px_qfq.csv --market data/idx_cyb.csv                    # 默认 balanced
$PY swing_strategy.py --csv data/px_qfq.csv --market data/idx_cyb.csv --preset defensive # 换档
```

| 预设 | 含义 | 301526 全样本 |
|---|---|---|
| `balanced`（默认） | 趋势 + 先手 A\|B1\|B2\|B3\|C | 966.5% / −32.4% / 33 笔 |
| `slim_dip` | 先手只留 B1+B2 | 861.6% / −35.3% / 24 笔 |
| `trend_only` | 不做先手 | 822.8% / **−28.9%** / 5 笔 |
| `balanced_margin` | 先手需沪市两融20日>0 | 931.5% / 21 笔（交易−36%） |
| `defensive` | 买带0/卖带5%，无先手 | 770.3% / −33.1% / 6 笔 |
| `aggressive_trail` | 满仓+25%追踪（无趋势过滤） | 711.9% / −56.2% |

**改动代码后先跑回归**：`balanced` 必须给出 **966.47% / −32.41% / 33 笔**。对不上就是改错了。

也可走仓库自带回测框架（用于与其它策略统一评测，需数据桥 + run 根，见 `STRATEGY.md` §5.5）：

```bash
cd <repo>/agent && VIBE_TRADING_ALLOWED_RUN_ROOTS=<repo>/reports \
  <repo>/.venv/bin/python -m backtest.runner <repo>/reports/301526_swing_study/run
# 交叉校验锚点: trade_count=33, win_rate=0.5758, max_drawdown=-0.3240
```

## 任务 C：换标的？先体检，否则别用

```bash
$PY swing_strategy.py --csv <目标.csv> --market data/idx_cyb.csv --check
$PY swing_strategy.py --batch data/peers/ --market data/idx_cyb.csv --check   # 批量
```

判定列是**捕获率 = 策略收益 / 买入持有收益**（纯趋势口径，与报告 §12 同口径）：

| 捕获率 | 结论 | 处置 |
|---|---|---|
| **> 0.7** | 适配 | 可用完整配置（含先手层） |
| **0.4 ~ 0.7** | 只作风控层 | 接受收益让渡换回撤控制 |
| **< 0.4** | 不适用 | 改用满仓 + 2.0~2.5×ATR 追踪，或长期持有 |

**20 只同类标的捕获率中位仅 0.39**（回撤改善 18/20，收益改善 2/20）。
这套规则只在"长而干净的多段趋势"上赚钱 —— 复材 1.23、中际旭创 0.77 适配；
胜宏科技 0.10、新易盛 0.14、深南电路 0.17 完全不适用（趋势中反复剧烈洗盘，趋势过滤被反复打脸）。
**换标的必须先体检，不要假设能迁移。**

## 任务 D：更新数据

```bash
$PY fetch_data.py --only prices,margin,lhb,block,ann      # 增量，约 1 分钟
$PY run_swing.py                                          # 或直接 --signal
```

数据源/口径/踩坑见 `ashare-data-lab` 技能（本策略的数据层由它保障）。
生产侧同步研究报告用 `./scripts/sync_study.sh 301526_swing_study`（`deploy.sh` 有意排除 `reports/`）。

## 三条禁忌（都回测验证过，别做）

1. **不要按顶部信号减仓/清仓** —— 全样本 823% → 446%（减仓）/ 357%（清仓），回撤只从 −28.9%
   改善到 −24.5%/−37.2%。强趋势股上过早下车的代价远大于躲回撤的收益。
2. **不要用宏观/月份择时来提收益** —— 黄金/原油/美债/VIX/费半/纳指等 14 个变量对
   "先手层是否有效"的解释力 |Spearman| ≤ 0.23；唯一稳定的是"沪市两融20日>0"，
   它的价值是**砍交易数**不是提收益。
3. **不要用波动率归一化解决移植问题** —— 把阈值全改成按 ATR% 缩放，捕获率与固定版持平
   （0.36 vs 0.36），回撤更差。问题在标的趋势形态，不在阈值标定。

## 风险与现状

- **样本小**：单标的、556 个交易日、核心版仅 5 笔交易，置信区间很宽；
  2025/2026 形态在设计时都看过，"样本外"不是严格盲测。**不要把它当已验证的赚钱机器。**
- **解禁**：2026-12-28 解禁 23.66 亿股（占总股本 62.8%、占流通市值 168.5%）；
  参照 2024-12-26 那次解禁后 20 日 −15.4%。**建议 12 月前主动降档**，别等止损信号。
- **现状（2026-09-11）**：目标仓位 **0%（空仓）** —— 收盘 30.69 站上 MA20 仅 0.85%，
  MA20(30.43) 仍在 MA60(34.74) 下方。**这些数字会过期，以任务 A 的实跑为准。**

## 文件索引（`$ST` 下）

| 文件 | 用途 |
|---|---|
| `swing_strategy.py` | 策略本体（CLI + 可 import；6 档预设、体检、信号） |
| `STRATEGY.md` | **冻结规格书**：规则、预设、适用性体检、两种运行方式、局限 |
| `REPORT.md` | 完整研究 14 节（波段真值、信号研究、回测、可迁移性、宏观/海外因子、勘误 §14） |
| `signal_engine.py` / `run/` | 仓库回测框架入口（`SignalEngine` + run_dir） |
| `data/` | 数据（`px_qfq.csv` 主行情、`idx_cyb.csv` 大盘、`peers/` 横向样本） |
