---
name: easy-tdx
category: data-source
description: 通达信协议 A股实时行情 MCP（easy-tdx）。免费、无Key、无需通达信客户端。当需要A股实时报价快照、盘中市场情绪扫描（涨跌家数/涨停潮/板块主线/异动流）、行业概念板块下钻、个股资金流、缠论结构/技术指标快算、公告与财报三表核对时，优先调用 mcp_easytdx_* 工具。
---

# easy-tdx: 通达信协议实时行情 MCP

服务端已部署并注册在生产 trading-claw 的 `mcpServers`（键名 `easytdx`）。所有工具以 `mcp_easytdx_<工具名>` 前缀出现在会话中，输出 JSON，全部只读。数据来自通达信协议直连（免费、无 Key、无 IP 限流），由 MCP server 在本机子进程封装 easy-tdx CLI 实现。

## 什么场景调用（核心判断）

| 场景 | 调用 | 说明 |
|------|------|------|
| 用户问"XX现在多少钱/涨跌如何/估值多少" | `mcp_easytdx_quote` | 支持批量: `"000001,600519"`，含 PE/换手/市值/主力净流入 |
| 盘面情绪速览："今天市场怎么样" | `mcp_easytdx_market_stat` | 涨跌家数、涨停/跌停家数、两市成交额，零参数 |
| "哪些板块在涨/今日主线是什么" | `mcp_easytdx_board_ranking` | 行业(HY)/概念(GN)排行，含板块主力净流入 |
| 板块下钻找龙头 | `mcp_easytdx_board_members` | 传入板块代码(881xxx/880xxx)，成分股实时报价 |
| 个股属于什么概念/板块 | `mcp_easytdx_belong_board` | 反查所属板块 |
| 涨幅榜/成交额榜/换手率榜 | `mcp_easytdx_quote_list` | category: A/SH/SZ/KCB/CYB/BJ/ETF/HGT… |
| 盘中异动/涨停潮复盘 | `mcp_easytdx_unusual` | 封板/炸板/急拉/跳水事件流 |
| "主力资金在流入还是流出XX" | `mcp_easytdx_capital_flow` | ⚠️ 通达信口径，与东财/同花顺不可横向比 |
| 技术面快算："MACD金叉了吗/BOLL位置" | `mcp_easytdx_indicator` | 34 个指标，无需写 pandas 代码 |
| 缠论结构/买卖点/背驰 | `mcp_easytdx_chanlun` | 分型/笔/中枢/一二三类买卖点，支持次级别联立 |
| 分时/逐笔复盘 | `mcp_easytdx_tick` / `mcp_easytdx_transaction` | 大单动向、尾盘异动 |
| 分钟级 K 线 | `mcp_easytdx_kline` | 1MIN~MONTHLY，QFQ/HFQ 复权 |
| 排查异动事件："XX为什么涨" | `mcp_easytdx_announcement` | 巨潮公告（HTTP源，TDX 不通时也可用） |
| 财务快速核对 | `mcp_easytdx_finance_info` / `mcp_easytdx_f10` | 通达信单期快照 / 新浪三表 |
| easytdx 工具集体超时 | `mcp_easytdx_ping` | 先诊断 TDX 服务器连通性再重试 |

## 什么场景不要用

- **长历史回测/因子计算**：用内置 loader（tushare/baostock/warehouse），easy-tdx K 线上限 800 根且走实时协议。
- **港美股、期货实时行情**：本封装未暴露 easy-tdx 的 `ex` 扩展市场命令；用 iFind MCP（`mcp_hexin-*`）或 yfinance。
- **授权级深度基本面/研报**：用 iFind（同花顺）系列 MCP；easy-tdx 只有单期财务快照。
- **资金流横向对比**：通达信"主力净流入"口径与东财/同花顺不同，跨源对比只能看趋势不能比绝对值；iFind 资金流与 easy-tdx 资金流混用时必须在结论中注明口径。
- **需要逐档五档盘口的高频场景**：协议为轮询近似（约 3 秒延迟），非推送。

## 调用约定

- **代码格式**：直接给 6 位代码（`000001`/`600519`）即可，自动识别 SH/SZ/BJ；歧义品种（可转债 11x=SH、12x/15x=SZ）已按前缀路由，必要时显式写 `SZ 000001` / `600519.SH`。
- **盘中 vs 盘后**：收盘后调用 quote 返回全天快照（close=收盘价），unusual 保留当日事件流，均可正常复盘使用。
- **返回体量**：kline ≤800 根、quote_list ≤100 只、unusual ≤500 条，超限自动截断；分析结论只引用关键行，不要整表复述。
- **错误处理**：报"超时/退出码"时先用 `mcp_easytdx_ping` 确认连通性；ping 正常但单工具失败通常是该代码无数据（如退市/新股），换代码或用 `mcp_easytdx_symbol_info` 验证。

## 实现备注

- MCP server: `agent/src/tools/easytdx_mcp_server.py`（fastmcp stdio，封装 `python -m easy_tdx` CLI 子进程）。
- 依赖: 服务器 venv 内 `pip install easy-tdx`（>=1.30，要求 Python>=3.10）。
- 上游: https://github.com/handsomejustin/easy_tdx （MIT）。注册配置在操作员文件 `/var/lib/vibe/.vibe-trading/agent.json` → `mcpServers.easytdx`。
