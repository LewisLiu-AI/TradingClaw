# 飞书端部署指南（STAR50 预警打分）

> 生产服务器（47.100.42.183）上只有 vibe-trading 的 MCP/HTTP 服务，**没有 Agent 运行时**。
> 飞书对话对接的是云端 Agent（有自己的技能体系）。因此两件事分开做：
> ① 定时任务的**提示词**改成下方"生产版"（自包含，不依赖技能，直接可执行）；
> ② SKILL 安装到云端 Agent（见文末，二选一）。

---

## ① 定时任务提示词 · 生产版（复制以下全文，粘贴到飞书平台的定时任务/自动化配置）

```text
执行科创50利空预警的盘前打分流程（只读+打分，禁止任何交易操作）：

工作目录：/opt/vibe-trading/reports/star50_study（若不存在，改用 /Users/lewis/code/TradingClaw/reports/star50_study）

0. 更新指数数据：运行 curl -s --max-time 10 "https://qt.gtimg.cn/q=sh000688" | iconv -f GBK -t UTF-8，按 ~ 分割字段：[30]时间戳(YYYYMMDDHHMMSS)、[5]开盘、[33]最高、[34]最低、[3]收盘、[6]成交量。若该日期晚于 star50_index.csv 末行日期，则追加一行（date,open,high,low,close,volume，volume 用 [6] 原值）。若接口失败或日期不新于末行，跳过并注明。
1. 取隔夜与宏观读数（SOXX/QQQ 与汇率可用 curl -s -H "User-Agent: Mozilla/5.0" "https://query1.finance.yahoo.com/v8/finance/chart/<代码>?range=1mo&interval=1d" 解析 timestamp/close，代码：SOXX、QQQ、CNH=X；PE 分位与两融余额用 wind MCP：get_stock_fundamentals 问"科创50(000688.SH)当前市盈率TTM及其5年历史分位数"与"A股市场融资融券余额最近5个交易日"）：
   - 隔夜美股：SOXX（费半）与 QQQ 最新收盘日涨跌幅（%）
   - USDCNH 近10个自然日涨幅（%）
   - 科创50 PE(TTM) 5年历史分位数（%）
   - 两融余额5日降幅（%）
2. 事件扫描（详见工作目录内 HANDOFF_归因数据搜集任务.md §0.6，或按以下规则）：72h 内无中美关税/管制/制裁新公告→B1=0；无地缘军事升级→B2=0；前十大权重股无减持公告→E2=0；未来5日有中央级会议/重磅数据（如CPI/PPI/金融数据）→落地日起C1+1.5；未来10日权重股财报集中→C2+1；未来3日有美联储议息/美CPI/鲍威尔讲话→A3+1；未来30日科创板解禁市值占板块流通市值>3%→E3+1。
3. 打分：在该目录执行
   python3 daily_score.py --soxx <隔夜SOXX%> --qqq <隔夜QQQ%> --fx10d <USDCNH10日涨幅%> --pe-percentile <分位数> [--a3/--a1a/--b1/--b2/--c1/--c2/--d1-lever/--d2/--e1a/--e2/--e3/--e4 按扫描结果命中]
4. 汇报：总分、级别（Ⅰ绿0-2/Ⅱ黄3-5/Ⅲ橙6-8/Ⅳ红≥9）、仓位纪律、各因子读数与触发依据；若为橙色及以上，在回复开头用醒目方式标注"⚠️预警升级"。
数据缺失时如实标注"缺失"并继续可算部分，不要编造数值。当日若为A股节假日，说明"今日休市"即可。
```

**要点**：工作目录已改为生产路径 `/opt/vibe-trading/reports/star50_study`（服务器上数据已就绪，
今日 9/8 已按新数据入库，ep91 现为 8/19~9/08 累计 -11.16%）。这段提示词**自包含**——
即使不装 SKILL，任何 Agent 拿到它都能直接执行。

---

## ② SKILL 安装到飞书云端 Agent（可选增强，二选一）

**方式 A（推荐，一条消息完成）**：在飞书里对 Agent 发送：

> 请将以下内容保存为你的技能文件 ~/.zcode/skills/star50-warning/SKILL.md（目录不存在则创建），
> 保存后确认。内容如下：……（粘贴 reports/star50_study/SKILL.md 全文）……

**方式 B（平台界面）**：若你的 Agent 平台有"技能管理/导入"界面，直接上传
`reports/star50_study/SKILL.md`（在仓库与本机 ~/.zcode/skills/ 均有正本）。

装好后验证：对 Agent 说"科创50盘前打分"，它应自动加载技能并按标准流程执行。

---

## 环境对照

| | 开发机（macOS） | 生产服务器（47.100.42.183） |
|---|---|---|
| 工作目录 | /Users/lewis/code/TradingClaw/reports/star50_study | /opt/vibe-trading/reports/star50_study |
| Python | 3.9+ | 3.6.8（脚本已验证兼容） |
| PDF 导出 | Chrome 可用 | 无 Chrome，需开发机导出后同步 |
| SKILL | ~/.zcode/skills/star50-warning/ | /root/.zcode/skills/（服务器无人读取，仅存档）；**真正生效的是云端 Agent 技能库** |
| 定时 | ZCode cron（本机 08:30） | 飞书平台定时任务（提示词用上方①） |
