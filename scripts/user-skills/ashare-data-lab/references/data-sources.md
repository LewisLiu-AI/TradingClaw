# A股数据源可得性矩阵

> 实测时间 2026-09。**先看这张表再设计因子** —— 拿不到的变量不值得写代码。
> 「单位」「披露滞后」「停更」三列最容易导致静默错误。

## 1. 个股层面

| 数据 | 来源(本 skill 用法) | 覆盖 | 单位/口径 | 披露滞后 | 备注 |
|---|---|---|---|---|---|
| 日行情(不复权) | 东财 push2his `/kline` `fqt=2` | 全历史 | 元 | T 日收盘 | **首选**，失败退新浪 |
| 日行情(前复权) | 同上 `fqt=1` | 全历史 | 元 | T 日收盘 | 基准日=最新日，故因子末日=1 |
| 日行情(后复权) | 同上 `fqt=0` | 全历史 | 元 | T 日收盘 | 因子 > 1，非 1 属正常 |
| 日行情(兜底) | akshare `stock_zh_a_daily`(新浪) | 全历史 | 元 | T 日收盘 | ⚠️ **换手率是小数**；含 `outstanding_share` |
| 换手率 | 随行情 | — | ⚠️ 源不同口径不同 | — | 见 pitfalls #1 |
| 融资融券明细 | 东财 datacenter `RPTA_WEB_RZRQ_GGMX` | 全历史(实测 657 天) | 元 / % | **T 日晚间** | 硬数据；分析须 `shift(1)` |
| 大宗交易 | 东财 datacenter `RPT_DATA_BLOCKTRADE` | 全历史 | 元 / 折溢率 | **T 日晚间** | 席位字段 `BUYER_NAME`/`SELLER_NAME`(**文本**) |
| 龙虎榜 | akshare `stock_lhb_detail_em` | 按区间 | 元 | **T 日晚间** | 区间逐日抓，会触发代理限流 |
| 公告标题 | 东财 `np-anotice-stock.eastmoney.com` | 近年 | — | T 日 | 一天可多条 → **日期不唯一** |
| 股东户数 | akshare `stock_zh_a_gdhs_detail_em` | 全历史 | 户/元 | **季度+45天** | 低频，勿按日对齐 |
| 限售解禁 | akshare `stock_restricted_release_queue_em` | 全历史 | 股/元 | 事前公告 | 含未来日期 |
| 东财主力资金流 | 东财 push2his `/fflow/daykline` | ⚠️ **仅约 120 交易日** | 万元 | T 日收盘 | 推算指标，非交易所披露 |
| 个股新闻 | akshare `stock_news_em` | ⚠️ **仅最近约 10 条** | — | — | 历史消息靠公告标题重建 |

## 2. 市场 / 宏观层面

| 数据 | 来源 | 覆盖 | 单位 | 备注 |
|---|---|---|---|---|
| 指数(创业板指等) | 东财 `/kline` 或新浪 | 全历史 | 点 | 新浪无成交额，只有成交量 |
| 全市场两融(沪深合计) | akshare `macro_china_market_margin_sz/sh` | 2010 起 | 元 | ⚠️ 见 pitfalls #2：**深市缺 177 天** |
| 全市场两融(沪市单边) | 同上 `_sh` | 2010 起**完整** | 元 | **分析用这个**（占全市场约 51%） |
| 跨资产(黄金/WTI/美债10Y/美元/VIX/费半/纳指/铜/恒生) | yfinance: `GC=F`,`CL=F`,`^TNX`,`DX-Y.NYB`,`^VIX`,`^SOX`,`^IXIC`,`HG=F`,`^HSI` | 全历史 | 各自 | 美市 T 日收盘 = 北京 T+1 凌晨 → **无前视** |
| 北向**成交额** | HKEX `hkex.com.hk/eng/csm/DailyStat/data_tab_daily_YYYYMMDDe.js` | 按日 | **百万人民币** | 官方；逐日抓 |
| 北向**净买入** | ❌ **2024-08-19 起停止披露** | 至 2024-08-16 | — | 任何工具都取不到 |
| 南向 | 同上 HKEX | 按日 | 百万港币 | 完整（含 Buy/Sell 拆分） |
| 全市场涨跌家数 / 涨停家数 | ❌ 仅当日快照 | — | — | 无历史序列 |
| 券商一致预期 | 东财研报接口常 400 | — | — | 需另找源 |

## 3. 已停止或无历史的三类（别浪费时间）

1. **北向资金净买入** —— 2024-08-19 沪深港通信息披露机制调整后停发。HKEX 日度统计里北向只有
   `Total Turnover / Total Trade Count / DQB / ETF Turnover`；**南向才有 Buy/Sell Turnover**。
   所以北向连"买入−卖出"都算不出来，只能当**外资参与度**（成交额）用。
2. **全市场涨跌家数 / 涨停家数历史** —— akshare 只有 `stock_market_activity_legu` 当日快照。
3. **北向个股持股明细** —— `stock_hsgt_individual_em` 与全市场口径同一天（2024-08-16）截止。

## 4. HTTP 层注意事项

- **本地代理（如 127.0.0.1:7890）在密集请求下会断连**，表现为
  `ProxyError: Remote end closed connection without response`。
  对策：每个端点重试 4~5 次 + 指数退避；批量任务（如逐日龙虎榜）之间 sleep ≥1s。
- **东财 `push2his` 比 `datacenter-web` 更容易失败**。同样 URL 用 `requests` 直连可能成功，
  而 akshare 失败 —— 所以"首选直连 + 备用源"比"只用 akshare"稳。
- 新浪日线接口返回 GBK 编码与小数换手率；腾讯行情 `qt.gtimg.cn` 也是 GBK，
  字段按 `~` 分隔且索引固定（见 star50-warning skill 的实测索引表）。
