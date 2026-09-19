---
name: berkshire
category: other
description: "AI Berkshire 技能库导航。当用户提到「伯克希尔」（AI Berkshire / Berkshire 技能库）时，输出该技能库全部能力清单（格式：序号、SKILL，用途，适合场景）并引导下一步选择。触发词：伯克希尔/AI Berkshire/Berkshire/伯克希尔技能库/伯克希尔能做什么。注意：用户直接点名某个技能名或直接提出研究需求时，不要输出清单，直接加载对应技能执行。"
---

# AI Berkshire 技能库导航

本技能是 [ai-berkshire](https://github.com/xbtlin/ai-berkshire) 技能库在 TradingClaw 里的总入口。库里每个技能都已装入本 Agent，并带「数据加速层」（行情/财报/研报/新闻等优先走内置数据工具，原技能的网页抓取方式兜底）。

## 行为规则

1. **用户消息里出现「伯克希尔 / AI Berkshire」且没有附带具体研究任务** → 按下面模板**逐条输出能力清单**（每条独占一行，保持「序号、SKILL，用途，适合场景」格式，不要改写、不要省略），结尾加一句引导：「回复序号或技能名即可开始；也可以直接说需求，我来帮你选技能。」
2. **用户点名了某个技能（序号/技能名/明确说"用 XX 帮我…"）** → `load_skill` 加载该技能并直接开始执行，不输出清单。
3. **用户带着具体研究需求提到伯克希尔**（如"伯克希尔帮我研究一下腾讯"）→ 简短推荐 1-2 个适配技能并直接开始执行，不输出完整清单。
4. 输出清单本身也遵守下方飞书规则。

## 能力清单（回复模板）

1、investment-research，四大师综合深度分析，对一家上市公司进行全方位投资研究

2、investment-team，多Agent并行投研团队，4个Agent并行研究，最快速、最全面

3、management-deep-dive，管理层纵深研究，"买股票就是买人"——当管理层是核心变量时深挖

4、private-company-research，未上市公司深度研究，研究蚂蚁、SpaceX等信息稀缺的未上市公司

5、deep-company-series，8篇长文系列拆一家公司，公众号级深度系列，12万字从认知重置到决策闭环

6、earnings-review，财报精读（一手资料），只读原始财报，不依赖二手研报，像巴菲特一样读年报

7、earnings-team，财报精读团队 + 公众号发布，四大师并行解读财报 → 编辑润色 → 读者评审 → 可发布文章

8、industry-research，产业链全景扫描，研究一个行业的全部投资机会（按产业链环节切片）

9、industry-funnel，行业漏斗筛选，全市场 → 粗筛 ≤10 家 → 终选 3 家深度分析

10、quality-screen，去劣筛选（7条硬指标），快速排除非一流公司，支持个股/行业/指数/主题批量筛

11、bottleneck-hunter，供应链瓶颈猎手，从超级趋势出发，寻找产业链物理瓶颈和套利机会

12、era-alpha，时代α捕手，识别时代级高增长主线中的核心α，验证增长可持续性，给出介入与退出纪律

13、investment-checklist，巴菲特买入前 Checklist，六关快速筛选，10分钟决定是否值得深入

14、income-investment，收益型股票分析，区分可持续收益、机会型高息与收益率陷阱

15、portfolio-review，组合管理与优化，从"研究公司"升级到"管理组合"——仓位、集中度、再平衡

16、thesis-tracker，投资论文追踪，买入后的纪律系统：持续跟踪论文是否被证伪

17、thesis-drift，投资论文漂移检测，对比两份论文/报告，区分事实变化、估值变化与措辞变化

18、news-pulse，股价异动快速归因，股价大涨/大跌时10分钟搞清"发生了什么"

19、dyp-ask，段永平问答，以段永平的方式思考任何问题——商业、投资、人生

20、financial-data，财务数据获取与交叉验证规范，确保关键数据来自2个独立来源，误差>1%告警

21、wechat-article，微信公众号文章，作者、编辑、读者三Agent协作，产出可发布文章

## 选型速查（口头补充用，不打进清单）

- 要**快**：investment-team（4 Agent 并行）＞ investment-checklist（10 分钟）＞ quality-screen
- 要**深**：investment-research（单公司最深）／deep-company-series（12 万字系列）
- 只是想**问个问题**：dyp-ask；股价**突然大涨大跌**：news-pulse；**已经持仓**：thesis-tracker

## 飞书输出规则

若本会话来自飞书（或用户要求发到飞书）：能力清单与研究报告一律以 Markdown 直接作为回复正文输出——飞书渠道会自动渲染为交互卡片，超长内容自动分片成多张卡片；不要只回一个本地文件路径。报告文件同时照常存档（reports/）。
