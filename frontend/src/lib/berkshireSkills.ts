/**
 * AI Berkshire skill catalogue — the data behind the 巴菲特 workspace (/berkshire).
 *
 * The 21 skills below mirror `scripts/user-skills/*` (installed on the server by
 * scripts/deploy.sh into the service user's ~/.vibe-trading/skills/user). Keep the
 * `id` byte-identical to the skill directory name: it is passed to the agent as
 * `load_skill("<id>")`, so a typo silently degrades the run into "no skill found".
 *
 * UI copy lives here rather than in the i18n bundles on purpose: the upstream
 * library is Chinese-only, so the catalogue is not translated.
 */
import type { LucideIcon } from "lucide-react";
import {
  BookOpen,
  Building2,
  Calculator,
  ChartPie,
  Compass,
  FileSearch,
  FileText,
  Filter,
  GitCompare,
  HandCoins,
  Landmark,
  Layers,
  ListChecks,
  MessageCircleQuestion,
  Microscope,
  Newspaper,
  PenTool,
  Repeat2,
  ScrollText,
  ShieldCheck,
  Telescope,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react";

export type BerkshireCategoryId =
  | "deep"
  | "earnings"
  | "screen"
  | "industry"
  | "portfolio"
  | "output";

export interface BerkshireCategory {
  id: BerkshireCategoryId;
  label: string;
  blurb: string;
  icon: LucideIcon;
}

export interface BerkshireSkill {
  /** Skill directory name — must match scripts/user-skills/<id>/SKILL.md */
  id: string;
  /** Short Chinese name used on the card */
  name: string;
  /** One-line purpose (from the upstream capability table) */
  purpose: string;
  /** When to reach for it */
  scenario: string;
  category: BerkshireCategoryId;
  icon: LucideIcon;
  /** Searchable keywords beyond the name/purpose */
  tags: string[];
  /** What the user has to type in */
  needs: string;
  /** Example subject shown as a chip + used to prefill the modal */
  example: string;
  /** What comes out of the run */
  deliverable: string;
  /** Rough turnaround, copied from the skill's own framing */
  duration: string;
  /** Prompt sent to the agent; `${subject}` is replaced at launch */
  prompt: (subject: string) => string;
}

export const BERKSHIRE_CATEGORIES: BerkshireCategory[] = [
  {
    id: "deep",
    label: "深度研究",
    blurb: "把一家公司从生意、护城河到估值看透",
    icon: Microscope,
  },
  {
    id: "earnings",
    label: "财报精读",
    blurb: "只读一手财报，不被二手研报牵着走",
    icon: FileSearch,
  },
  {
    id: "screen",
    label: "筛选排查",
    blurb: "先排除不值得看的，再决定深不深挖",
    icon: Filter,
  },
  {
    id: "industry",
    label: "行业与趋势",
    blurb: "从产业链全景到时代级 α 的定位",
    icon: Layers,
  },
  {
    id: "portfolio",
    label: "组合与纪律",
    blurb: "买之后的跟踪、复盘与异动归因",
    icon: Repeat2,
  },
  {
    id: "output",
    label: "收益与输出",
    blurb: "股息视角、段永平式思考、可发布成稿",
    icon: PenTool,
  },
];

const RULE = "按技能自带的流程与输出模板执行，结论先行，关键数据注明来源与口径。";

export const BERKSHIRE_SKILLS: BerkshireSkill[] = [
  // ── 深度研究 ────────────────────────────────────────────────────────────
  {
    id: "investment-research",
    name: "四大师深度研究",
    purpose: "四大师综合深度分析，一家上市公司的全方位投资研究",
    scenario: "准备重仓、要一次把生意看懂看全的时候",
    category: "deep",
    icon: Telescope,
    tags: ["巴菲特", "芒格", "护城河", "估值", "深度"],
    needs: "公司名或股票代码；可选补充你关心的角度（估值 / 竞争 / 管理层）",
    example: "腾讯控股 00700",
    deliverable: "生意模式拆解 + 护城河评级 + 管理层评估 + 估值区间 + 买/不买结论",
    duration: "30–60 分钟",
    prompt: (s) =>
      `请先调用 load_skill("investment-research") 加载技能，然后对「${s}」做四大师综合深度分析：生意本质、护城河、管理层、估值四层拆解，最后给出买/不买结论与可执行的价格区间。${RULE}`,
  },
  {
    id: "investment-team",
    name: "多 Agent 并行投研",
    purpose: "4 个 Agent 并行研究，最快速、最全面",
    scenario: "时间紧但要覆盖面，需要多个视角同时开工",
    category: "deep",
    icon: Users,
    tags: ["并行", "团队", "多视角", "快速"],
    needs: "公司名或股票代码；一句话说明你最想回答的问题",
    example: "宁德时代 300750，现在贵不贵",
    deliverable: "四条独立研究线并行输出 + 交叉验证 + 汇总结论",
    duration: "20–40 分钟",
    prompt: (s) =>
      `请先调用 load_skill("investment-team") 加载技能，按多 Agent 并行投研团队的方式研究「${s}」：分派 4 个角色并行取数与分析，交叉核对分歧，最后汇总成一份结论明确的报告。${RULE}`,
  },
  {
    id: "management-deep-dive",
    name: "管理层纵深研究",
    purpose: "「买股票就是买人」——当管理层是核心变量时深挖",
    scenario: "重资产转型、家族企业、关键人依赖、治理结构存疑",
    category: "deep",
    icon: Landmark,
    tags: ["管理层", "治理", "诚信", "资本配置"],
    needs: "公司名 / 代码；如果知道，补一句你怀疑的具体点",
    example: "伯克希尔 BRK.B 的资本配置能力",
    deliverable: "履历与持股穿透 + 历年承诺兑现 + 资本配置记录 + 治理风险清单",
    duration: "30–50 分钟",
    prompt: (s) =>
      `请先调用 load_skill("management-deep-dive") 加载技能，对「${s}」做管理层纵深研究：履历与利益一致性、历年公开承诺的兑现率、资本配置决策质量、治理与关键人风险。${RULE}`,
  },
  {
    id: "private-company-research",
    name: "未上市公司研究",
    purpose: "研究蚂蚁、SpaceX 等信息稀缺的未上市公司",
    scenario: "一级市场标的、IPO 前研究、并购尽调前置",
    category: "deep",
    icon: Building2,
    tags: ["一级市场", "未上市", "私募", "尽调"],
    needs: "公司名；有融资轮次 / 估值 / 股东信息更好",
    example: "SpaceX 的最新估值与星链经济性",
    deliverable: "信息拼图（融资、股东、业务）+ 可比公司估值 + 关键不确定性与证伪点",
    duration: "30–60 分钟",
    prompt: (s) =>
      `请先调用 load_skill("private-company-research") 加载技能，研究未上市公司「${s}」：把分散的融资、股东、业务与竞争信息拼成完整图景，用可比公司法估区间，并列出最关键的三个不确定性与证伪信号。${RULE}`,
  },
  {
    id: "deep-company-series",
    name: "8 篇深度系列",
    purpose: "8 篇长文系列拆一家公司，12 万字从认知重置到决策闭环",
    scenario: "要做成公众号级系列、把认知彻底重装一遍",
    category: "deep",
    icon: BookOpen,
    tags: ["系列", "长文", "公众号", "12 万字"],
    needs: "公司名；可以指定先写第几篇",
    example: "拼多多，先出全系列规划 + 第 1 篇",
    deliverable: "8 篇系列大纲 + 首篇正文（一次跑不完会分批续写）",
    duration: "单篇 30–60 分钟",
    prompt: (s) =>
      `请先调用 load_skill("deep-company-series") 加载技能，为「${s}」规划 8 篇系列长文并开始写第 1 篇：先给全系列目录与每篇要解决的问题，再按技能模板产出首篇正文。${RULE}`,
  },

  // ── 财报精读 ────────────────────────────────────────────────────────────
  {
    id: "earnings-review",
    name: "财报精读",
    purpose: "只读原始财报，不依赖二手研报，像巴菲特一样读年报",
    scenario: "财报刚出、想看数字背后的真实经营变化",
    category: "earnings",
    icon: ScrollText,
    tags: ["年报", "季报", "一手资料", "现金流"],
    needs: "公司名 / 代码；可指定报告期（如 2025Q3、2025 年报）",
    example: "贵州茅台 600519 2025 三季报",
    deliverable: "三张表逐项拆解 + 附注里的异常点 + 经营质量结论",
    duration: "20–40 分钟",
    prompt: (s) =>
      `请先调用 load_skill("earnings-review") 加载技能，精读「${s}」的原始财报（优先一手报表与附注，不用二手研报代替）：利润表、资产负债表、现金流量表逐项看，标出异常科目与会计质量疑点，给出经营质量结论。${RULE}`,
  },
  {
    id: "earnings-team",
    name: "财报精读团队 + 成稿",
    purpose: "四大师并行解读财报 → 编辑润色 → 读者评审 → 可发布文章",
    scenario: "既要读得深，也要一篇能直接发出去的文章",
    category: "earnings",
    icon: Users,
    tags: ["财报", "多角色", "公众号", "成稿"],
    needs: "公司名 / 代码 + 报告期；是否直接出公众号稿",
    example: "美团 2025Q3 财报，出一篇可发布文章",
    deliverable: "四视角解读 + 编辑润色稿 + 读者视角挑刺后的终稿",
    duration: "30–50 分钟",
    prompt: (s) =>
      `请先调用 load_skill("earnings-team") 加载技能，围绕「${s}」组织财报精读团队：四大师并行解读 → 编辑润色 → 读者评审挑刺 → 输出一篇可直接发布的文章（同时保留解读要点）。${RULE}`,
  },
  {
    id: "financial-data",
    name: "财务数据交叉验证",
    purpose: "关键数据必须来自 2 个独立来源，误差 >1% 告警",
    scenario: "要引用数字写报告、做模型前先对齐口径",
    category: "earnings",
    icon: Calculator,
    tags: ["数据口径", "交叉验证", "误差", "核数"],
    needs: "公司名 / 代码 + 要核对的具体指标（营收、净利、ROE…）",
    example: "核对比亚迪近三年营收与经营现金流",
    deliverable: "双来源对照表 + 差异说明 + 采用值与理由",
    duration: "10–20 分钟",
    prompt: (s) =>
      `请先调用 load_skill("financial-data") 加载技能，对「${s}」的关键财务数据做双来源交叉验证：列出每个指标的来源 A/B、口径差异、误差百分比，超过 1% 的必须解释原因并给出最终采用值。${RULE}`,
  },

  // ── 筛选排查 ────────────────────────────────────────────────────────────
  {
    id: "investment-checklist",
    name: "买入前 Checklist",
    purpose: "巴菲特买入前六关快速筛选，10 分钟决定是否值得深入",
    scenario: "刚看到一只票，先判断值不值得花时间",
    category: "screen",
    icon: ListChecks,
    tags: ["六关", "10 分钟", "值不值得", "快速"],
    needs: "公司名 / 代码；一句话说清你想买它的理由",
    example: "海天味业 603288，我想长期持有",
    deliverable: "六关逐条过/不过 + 一票否决项 + 是否进入深度研究的建议",
    duration: "5–10 分钟",
    prompt: (s) =>
      `请先调用 load_skill("investment-checklist") 加载技能，用巴菲特买入前六关 Checklist 快速筛「${s}」：逐关给出过/不过及依据，指出是否存在一票否决项，最后明确「值得深入 / 不值得」并说明理由。${RULE}`,
  },
  {
    id: "quality-screen",
    name: "去劣筛选（7 条硬指标）",
    purpose: "7 条硬指标快速排除非一流公司，支持个股 / 行业 / 指数 / 主题批量筛",
    scenario: "一篮子标的要先砍掉大部分，或给行业做体检",
    category: "screen",
    icon: ShieldCheck,
    tags: ["ROE", "现金流", "去劣", "批量"],
    needs: "标的列表 / 行业 / 指数 / 主题，任选一种",
    example: "A 股白酒板块全部上市公司",
    deliverable: "逐条指标通过矩阵 + 淘汰名单与原因 + 留下的候选池",
    duration: "10–20 分钟",
    prompt: (s) =>
      `请先调用 load_skill("quality-screen") 加载技能，对「${s}」执行 7 条硬指标去劣筛选：给出每家的指标通过矩阵、淘汰名单及具体原因、最后留下的候选池，并按质量排序。${RULE}`,
  },

  // ── 行业与趋势 ──────────────────────────────────────────────────────────
  {
    id: "industry-research",
    name: "产业链全景扫描",
    purpose: "研究一个行业的全部投资机会（按产业链环节切片）",
    scenario: "进入一个陌生行业，先建立地图再谈个股",
    category: "industry",
    icon: Compass,
    tags: ["产业链", "全景", "环节", "机会地图"],
    needs: "行业名；可选限定市场（A 股 / 港股 / 美股）",
    example: "人形机器人产业链",
    deliverable: "产业链分层图 + 各环节价值量与格局 + 每环节的代表公司与卡点",
    duration: "30–60 分钟",
    prompt: (s) =>
      `请先调用 load_skill("industry-research") 加载技能，对「${s}」做产业链全景扫描：按上中下游环节切片，给出各环节的价值量、竞争格局、代表公司、进入壁垒与投资机会，最后指出最值得深入的两个环节。${RULE}`,
  },
  {
    id: "industry-funnel",
    name: "行业漏斗筛选",
    purpose: "全市场 → 粗筛 ≤10 家 → 终选 3 家深度分析",
    scenario: "只看一个行业，但要从几十家里收敛到 3 家",
    category: "industry",
    icon: Filter,
    tags: ["漏斗", "收敛", "3 家", "精选"],
    needs: "行业名 + 你的筛选偏好（成长 / 分红 / 低估）",
    example: "半导体设备，偏成长",
    deliverable: "全市场清单 → ≤10 家粗筛 → 3 家深度对比与首选",
    duration: "30–60 分钟",
    prompt: (s) =>
      `请先调用 load_skill("industry-funnel") 加载技能，对「${s}」做行业漏斗筛选：先列全市场标的，再用硬指标粗筛到不超过 10 家，最后对 3 家做深度对比，给出首选与理由。${RULE}`,
  },
  {
    id: "bottleneck-hunter",
    name: "供应链瓶颈猎手",
    purpose: "从超级趋势出发，寻找产业链物理瓶颈和套利机会",
    scenario: "趋势很热但不知道谁真正卡脖子、谁真能涨价",
    category: "industry",
    icon: Zap,
    tags: ["卡脖子", "产能", "涨价", "套利"],
    needs: "趋势 / 主题（如 AI 算力、电网改造）",
    example: "AI 数据中心供电",
    deliverable: "瓶颈环节定位 + 供需缺口测算 + 受益标的与验证指标",
    duration: "30–50 分钟",
    prompt: (s) =>
      `请先调用 load_skill("bottleneck-hunter") 加载技能，从「${s}」这条超级趋势出发，逐层拆产业链找出物理瓶颈（产能、良率、认证、资源），测算供需缺口，指出最直接的受益环节与标的，并给出可跟踪的验证指标。${RULE}`,
  },
  {
    id: "era-alpha",
    name: "时代 α 捕手",
    purpose: "识别时代级高增长主线中的核心 α，验证可持续性，给出介入与退出纪律",
    scenario: "判断一条主线是三年景气还是十年趋势",
    category: "industry",
    icon: TrendingUp,
    tags: ["时代主线", "α", "可持续性", "退出纪律"],
    needs: "主线 / 主题名；你关心的持有周期",
    example: "AI 应用侧，3 年周期",
    deliverable: "主线定性 + 核心 α 标的 + 增长可持续性证据 + 介入/退出纪律",
    duration: "30–50 分钟",
    prompt: (s) =>
      `请先调用 load_skill("era-alpha") 加载技能，判断「${s}」是否构成时代级主线：拆解驱动因素与持续时间，找出其中真正的核心 α，用数据验证增长可持续性，最后给出介入条件、仓位建议与退出纪律。${RULE}`,
  },

  // ── 组合与纪律 ──────────────────────────────────────────────────────────
  {
    id: "portfolio-review",
    name: "组合复盘与优化",
    purpose: "从「研究公司」升级到「管理组合」——仓位、集中度、再平衡",
    scenario: "持仓越来越杂，需要一次结构性体检",
    category: "portfolio",
    icon: ChartPie,
    tags: ["仓位", "集中度", "再平衡", "相关性"],
    needs: "持仓清单（代码 + 权重 / 市值 + 成本价，有多少给多少）",
    example: "我的 8 只持仓，帮我看看集中度和再平衡",
    deliverable: "仓位与集中度诊断 + 隐性相关性与风险叠加 + 再平衡动作清单",
    duration: "20–40 分钟",
    prompt: (s) =>
      `请先调用 load_skill("portfolio-review") 加载技能，复盘我的组合：${s}。诊断仓位结构、单一风险暴露、隐性相关性，给出具体的再平衡动作（买/卖/减到多少），并说明每一步的理由。${RULE}`,
  },
  {
    id: "thesis-tracker",
    name: "投资论文追踪",
    purpose: "买入后的纪律系统：持续跟踪论文是否被证伪",
    scenario: "已经持仓，需要定期检查买入理由还成不成立",
    category: "portfolio",
    icon: Repeat2,
    tags: ["论文", "证伪", "持仓", "季度复核"],
    needs: "公司 + 当初的买入理由（贴原文最好）",
    example: "持有紫金矿业，理由是铜金量增 + 成本优势",
    deliverable: "论文逐条打分 + 新证据 + 证伪/维持/加仓的判断",
    duration: "20–30 分钟",
    prompt: (s) =>
      `请先调用 load_skill("thesis-tracker") 加载技能，跟踪「${s}」的投资论文：把原始买入理由拆成可验证的条目，用最新数据逐条打分（成立 / 存疑 / 已证伪），指出最需要警惕的一条，并给出持有、减仓或加仓的结论。${RULE}`,
  },
  {
    id: "thesis-drift",
    name: "投资论文漂移检测",
    purpose: "对比两份论文/报告，区分事实变化、估值变化与措辞变化",
    scenario: "半年后回看旧报告，想知道自己到底改了什么主意",
    category: "portfolio",
    icon: GitCompare,
    tags: ["漂移", "对比", "措辞", "自我审查"],
    needs: "两份文本（旧报告 + 新报告），或让我找同一标的的两期报告",
    example: "对比我对东方财富 2024 与 2026 的两份判断",
    deliverable: "三分类差异表（事实 / 估值 / 措辞）+ 漂移性质判定 + 需要补的证据",
    duration: "10–20 分钟",
    prompt: (s) =>
      `请先调用 load_skill("thesis-drift") 加载技能，对「${s}」做投资论文漂移检测：逐条对比两期判断，把差异归类为事实变化、估值假设变化或纯措辞变化，判定这是理性更新还是事后合理化，并列出需要补的证据。${RULE}`,
  },
  {
    id: "news-pulse",
    name: "股价异动归因",
    purpose: "大涨/大跌时 10 分钟搞清「发生了什么」",
    scenario: "盘中突然拉涨或跳水，需要快速判断是噪音还是拐点",
    category: "portfolio",
    icon: Newspaper,
    tags: ["异动", "为什么涨", "为什么跌", "10 分钟"],
    needs: "公司名 / 代码 + 异动方向与幅度（如今天 -8%）",
    example: "某股今天跌 9%，什么原因",
    deliverable: "事件时间线 + 主因排序与证据 + 对基本面的实际影响 + 是否要动手",
    duration: "5–10 分钟",
    prompt: (s) =>
      `请先调用 load_skill("news-pulse") 加载技能，对「${s}」做股价异动归因：拉出事件时间线，把可能原因按证据强度排序，区分情绪/资金面与基本面，判断影响是否可持续，最后给出要不要动手的建议。${RULE}`,
  },

  // ── 收益与输出 ──────────────────────────────────────────────────────────
  {
    id: "income-investment",
    name: "收益型股票分析",
    purpose: "区分可持续收益、机会型高息与收益率陷阱",
    scenario: "想靠股息拿现金流，又怕踩到高息陷阱",
    category: "output",
    icon: HandCoins,
    tags: ["股息", "红利", "陷阱", "现金流"],
    needs: "公司名 / 代码，或一组高股息候选",
    example: "长江电力 600900 的股息可持续性",
    deliverable: "分红能力拆解 + 股息可持续性评级 + 陷阱识别 + 合理买入价",
    duration: "20–30 分钟",
    prompt: (s) =>
      `请先调用 load_skill("income-investment") 加载技能，分析「${s}」的收益型投资价值：用自由现金流、派息率、负债与资本开支判断股息可持续性，区分可持续收益、机会型高息与收益率陷阱，给出合理买入价区间。${RULE}`,
  },
  {
    id: "dyp-ask",
    name: "段永平问答",
    purpose: "以段永平的方式思考任何问题——商业、投资、人生",
    scenario: "想听「大道」会怎么问、怎么答，而不是标准研报腔",
    category: "output",
    icon: MessageCircleQuestion,
    tags: ["段永平", "大道", "本分", "平常心"],
    needs: "任何问题：一家公司、一个决策、一段纠结",
    example: "现在该不该把仓位集中到一家公司",
    deliverable: "段永平式追问 + 直白回答 + 他会盯的那两个变量",
    duration: "即时–10 分钟",
    prompt: (s) =>
      `请先调用 load_skill("dyp-ask") 加载技能，用段永平的思维方式回答：「${s}」。先还原他会先问的那几个问题，再给出直白、不绕弯的回答，并指出他最在意的变量。${RULE}`,
  },
  {
    id: "wechat-article",
    name: "公众号成稿",
    purpose: "作者、编辑、读者三 Agent 协作，产出可发布文章",
    scenario: "研究做完了，要变成一篇能发出去的文章",
    category: "output",
    icon: FileText,
    tags: ["公众号", "成稿", "编辑", "读者视角"],
    needs: "主题或已有素材（可贴研究结论 / 报告路径）",
    example: "把上面这份宁德时代研究写成公众号文章",
    deliverable: "作者初稿 → 编辑润色 → 读者视角挑刺 → 终稿 + 标题备选",
    duration: "20–40 分钟",
    prompt: (s) =>
      `请先调用 load_skill("wechat-article") 加载技能，围绕「${s}」走完作者 → 编辑 → 读者三 Agent 流程，产出一篇可直接发布的公众号文章：给 3 个标题备选、正文、以及一段摘要。${RULE}`,
  },
];

/** Subject used when the hero "auto" mode runs: let the agent route itself. */
export const AUTO_PROMPT = (subject: string) =>
  `从 AI Berkshire 技能库中选择最合适的一个技能（用 load_skill 加载后严格执行），处理这个需求：「${subject}」。` +
  `开头先用一行说明你选了哪个技能、为什么。${RULE}`;

/** Hero shortcut chips: the four entry points people actually use. */
export const QUICK_PICKS: { label: string; skillId: string; example: string }[] = [
  { label: "10 分钟判断值不值得", skillId: "investment-checklist", example: "海天味业 603288" },
  { label: "一次看透一家公司", skillId: "investment-research", example: "腾讯控股 00700" },
  { label: "财报刚出，读原文", skillId: "earnings-review", example: "贵州茅台 600519 2025 三季报" },
  { label: "今天为什么大跌", skillId: "news-pulse", example: "某持仓今天跌 9%" },
];

export const BERKSHIRE_TOTAL = BERKSHIRE_SKILLS.length;

export function getSkill(id: string): BerkshireSkill | undefined {
  return BERKSHIRE_SKILLS.find((s) => s.id === id);
}

export function skillsByCategory(category: BerkshireCategoryId): BerkshireSkill[] {
  return BERKSHIRE_SKILLS.filter((s) => s.category === category);
}
