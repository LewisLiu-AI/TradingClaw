import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowRight,
  Clock,
  Database,
  Landmark,
  Loader2,
  Play,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { api, type SessionItem } from "@/lib/api";
import {
  AUTO_PROMPT,
  BERKSHIRE_CATEGORIES,
  BERKSHIRE_SKILLS,
  BERKSHIRE_TOTAL,
  QUICK_PICKS,
  getSkill,
  type BerkshireCategoryId,
  type BerkshireSkill,
} from "@/lib/berkshireSkills";
import { cn } from "@/lib/utils";

/** Prefix on session titles created from this page — powers 最近研究. */
const SESSION_PREFIX = "巴菲特 · ";

type CategoryFilter = "all" | BerkshireCategoryId;

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "";
  const diff = Date.now() - ts;
  const min = Math.floor(diff / 60_000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} 天前`;
  return new Date(ts).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

export function Berkshire() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [active, setActive] = useState<{ skill: BerkshireSkill; subject: string } | null>(null);
  const [heroSubject, setHeroSubject] = useState("");
  const [heroSkill, setHeroSkill] = useState<string>("auto");
  const [launching, setLaunching] = useState(false);
  const [recent, setRecent] = useState<SessionItem[]>([]);
  const [recentLoading, setRecentLoading] = useState(true);
  /** null = unknown (do not block the UI); otherwise skill id → installed & enabled */
  const [installed, setInstalled] = useState<Record<string, boolean> | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const subjectRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    api
      .listSessions()
      .then((list) => {
        const items = (Array.isArray(list) ? list : []).filter((s) =>
          (s.title || "").startsWith(SESSION_PREFIX),
        );
        setRecent(items.slice(0, 8));
      })
      .catch(() => setRecent([]))
      .finally(() => setRecentLoading(false));

    // Soft check: the page still works if the plugins endpoint is unavailable.
    api
      .listPlugins()
      .then((payload) => {
        const map: Record<string, boolean> = {};
        for (const skill of payload.skills ?? []) map[skill.name] = skill.enabled;
        setInstalled(map);
      })
      .catch(() => setInstalled(null));
  }, []);

  const available = (id: string) => (installed ? installed[id] === true : true);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return BERKSHIRE_SKILLS.filter((skill) => {
      if (category !== "all" && skill.category !== category) return false;
      if (!needle) return true;
      const haystack = `${skill.name} ${skill.id} ${skill.purpose} ${skill.scenario} ${skill.tags.join(" ")}`;
      return haystack.toLowerCase().includes(needle);
    });
  }, [query, category]);

  const groups = useMemo(
    () =>
      BERKSHIRE_CATEGORIES.map((cat) => ({
        cat,
        items: visible.filter((skill) => skill.category === cat.id),
      })).filter((group) => group.items.length > 0),
    [visible],
  );

  const missingCount = installed
    ? BERKSHIRE_SKILLS.filter((skill) => !installed[skill.id]).length
    : 0;

  const launch = async (skillId: string | null, rawSubject: string) => {
    const subject = rawSubject.trim();
    if (!subject) {
      toast.error("先写一句要研究什么，比如公司名、代码或你的问题");
      return;
    }
    const skill = skillId ? getSkill(skillId) : undefined;
    if (skill && !available(skill.id)) {
      toast.error(`技能 ${skill.id} 未启用，先到「插件」页面开启`);
      return;
    }
    setLaunching(true);
    try {
      const title = `${SESSION_PREFIX}${skill ? skill.name : "自动选技能"} · ${subject}`.slice(0, 50);
      const session = await api.createSession(title);
      const prompt = skill ? skill.prompt(subject) : AUTO_PROMPT(subject);
      await api.sendMessage(session.session_id, prompt);
      setActive(null);
      navigate(`/agent?session=${session.session_id}`);
    } catch (error) {
      toast.error(`启动失败：${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
      setLaunching(false);
    }
  };

  const openSkill = (skill: BerkshireSkill, subject = "") => {
    setActive({ skill, subject: subject || skill.example });
  };

  // Esc closes the dialog; focus the subject box on open.
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setActive(null);
    };
    document.addEventListener("keydown", onKey);
    const timer = window.setTimeout(() => {
      subjectRef.current?.focus();
      subjectRef.current?.select();
    }, 40);
    return () => {
      document.removeEventListener("keydown", onKey);
      window.clearTimeout(timer);
    };
  }, [active]);

  return (
    <div className="mx-auto max-w-7xl px-5 py-6 md:px-8 md:py-8">
      {/* ── Hero ─────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden rounded-2xl border bg-card">
        <div className="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-primary/10 blur-3xl" />
        <div className="pointer-events-none absolute -left-24 bottom-0 h-52 w-52 rounded-full bg-primary/5 blur-3xl" />
        <Landmark className="pointer-events-none absolute -bottom-8 right-6 h-40 w-40 text-primary/5" />

        <div className="relative grid gap-7 p-5 md:p-7 xl:grid-cols-[minmax(0,1fr)_minmax(0,400px)] xl:items-center">
          <div>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/25 bg-primary/10 px-2.5 py-1 text-[11px] font-medium text-primary">
              <Landmark className="h-3 w-3" />
              AI BERKSHIRE · {BERKSHIRE_TOTAL} 个技能
            </span>
            <h1 className="mt-3 text-2xl font-bold tracking-tight md:text-[28px]">巴菲特</h1>
            <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">
              把「先算清楚再出手」的投研流程做成一排可调用的技能：从 10 分钟排雷，到财报原文精读、
              产业链漏斗，再到 8 篇深度系列。选一个技能、填一个标的，直接在智能体里开跑。
            </p>
            <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-[11px] text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <Database className="h-3.5 w-3.5 text-primary/70" />
                数据加速层：行情 / 财报 / 研报优先走内置工具
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5 text-primary/70" />
                报告自动存档 reports/
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-primary/70" />
                结论可追问，全流程可回看
              </span>
            </div>
          </div>

          {/* Quick start */}
          <div className="rounded-xl border bg-background/70 p-4">
            <p className="text-xs font-medium text-muted-foreground">一句话开跑</p>
            <form
              className="mt-2 space-y-2"
              onSubmit={(e) => {
                e.preventDefault();
                void launch(heroSkill === "auto" ? null : heroSkill, heroSubject);
              }}
            >
              <input
                value={heroSubject}
                onChange={(e) => setHeroSubject(e.target.value)}
                placeholder="公司 / 行业 / 你的问题，如：腾讯 00700 现在贵不贵"
                className="w-full rounded-lg border bg-card px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground/60 focus:border-primary/60 focus:ring-2 focus:ring-primary/15"
              />
              <div className="flex gap-2">
                <select
                  value={heroSkill}
                  onChange={(e) => setHeroSkill(e.target.value)}
                  className="min-w-0 flex-1 rounded-lg border bg-card px-2 py-2 text-xs outline-none focus:border-primary/60 focus:ring-2 focus:ring-primary/15"
                  aria-label="选择技能"
                >
                  <option value="auto">自动选技能（推荐）</option>
                  {BERKSHIRE_CATEGORIES.map((cat) => (
                    <optgroup key={cat.id} label={cat.label}>
                      {BERKSHIRE_SKILLS.filter((s) => s.category === cat.id).map((skill) => (
                        <option key={skill.id} value={skill.id}>
                          {skill.name}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
                <button
                  type="submit"
                  disabled={launching}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-xs font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-60"
                >
                  {launching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                  开始研究
                </button>
              </div>
            </form>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {QUICK_PICKS.map((pick) => {
                const skill = getSkill(pick.skillId);
                if (!skill) return null;
                return (
                  <button
                    key={pick.skillId}
                    type="button"
                    onClick={() => openSkill(skill, pick.example)}
                    className="rounded-full border bg-card px-2.5 py-1 text-[11px] text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
                  >
                    {pick.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </section>

      {/* ── Filters ──────────────────────────────────────────────────── */}
      <div className="mt-6 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="relative w-full lg:max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜技能 / 场景 / 关键词"
            className="w-full rounded-lg border bg-card py-2 pl-9 pr-8 text-sm outline-none transition placeholder:text-muted-foreground/60 focus:border-primary/60 focus:ring-2 focus:ring-primary/15"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground"
              aria-label="清空搜索"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        <div className="flex flex-wrap gap-1.5">
          <FilterChip active={category === "all"} onClick={() => setCategory("all")}>
            全部 {BERKSHIRE_TOTAL}
          </FilterChip>
          {BERKSHIRE_CATEGORIES.map((cat) => (
            <FilterChip
              key={cat.id}
              active={category === cat.id}
              onClick={() => setCategory(cat.id)}
            >
              {cat.label} {BERKSHIRE_SKILLS.filter((s) => s.category === cat.id).length}
            </FilterChip>
          ))}
        </div>
      </div>

      {/* ── Skills + rail ────────────────────────────────────────────── */}
      <div className="mt-5 grid gap-6 xl:grid-cols-[minmax(0,1fr)_264px]">
        <div className="min-w-0">
          {groups.length === 0 ? (
            <div className="rounded-xl border border-dashed bg-card/50 px-6 py-14 text-center">
              <p className="text-sm font-medium">没有匹配的技能</p>
              <p className="mt-1 text-xs text-muted-foreground">
                换个关键词试试，比如「财报」「股息」「异动」「漏斗」。
              </p>
            </div>
          ) : (
            <div className="space-y-7">
              {groups.map(({ cat, items }) => {
                const CatIcon = cat.icon;
                return (
                  <section key={cat.id}>
                    <div className="mb-3 flex items-baseline gap-2">
                      <CatIcon className="h-4 w-4 shrink-0 self-center text-primary" />
                      <h2 className="text-sm font-semibold">{cat.label}</h2>
                      <span className="text-[11px] text-muted-foreground/70">{items.length}</span>
                      <span className="text-[11px] text-muted-foreground/30">·</span>
                      <span className="truncate text-[11px] text-muted-foreground/70">
                        {cat.blurb}
                      </span>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-[repeat(auto-fill,minmax(258px,1fr))]">
                      {items.map((skill) => (
                        <SkillCard
                          key={skill.id}
                          skill={skill}
                          available={available(skill.id)}
                          onOpen={() => openSkill(skill)}
                        />
                      ))}
                    </div>
                  </section>
                );
              })}
            </div>
          )}
        </div>

        <aside className="space-y-4 self-start xl:sticky xl:top-4">
          <div className="rounded-xl border bg-card p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold">最近研究</h2>
              <button
                type="button"
                onClick={() => navigate("/agent")}
                className="text-[11px] text-muted-foreground hover:text-foreground"
              >
                全部会话
              </button>
            </div>
            <div className="mt-2 space-y-0.5">
              {recentLoading ? (
                <div className="space-y-1.5 py-1">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-8 animate-pulse rounded-md bg-muted/50" />
                  ))}
                </div>
              ) : recent.length === 0 ? (
                <p className="py-2 text-[11px] leading-relaxed text-muted-foreground/70">
                  还没有从这里发起的研报。选一个技能开跑，结束后会出现在这里。
                </p>
              ) : (
                recent.map((session) => (
                  <button
                    key={session.session_id}
                    type="button"
                    onClick={() => navigate(`/agent?session=${session.session_id}`)}
                    className="block w-full rounded-md px-2 py-1.5 text-left transition hover:bg-muted"
                  >
                    <span className="block truncate text-[11px]">
                      {(session.title || "").replace(SESSION_PREFIX, "")}
                    </span>
                    <span className="mt-0.5 block text-[10px] text-muted-foreground/60">
                      {timeAgo(session.updated_at || session.created_at)}
                    </span>
                  </button>
                ))
              )}
            </div>
          </div>

          <div className="rounded-xl border bg-card p-4">
            <h2 className="text-xs font-semibold">怎么用</h2>
            <ol className="mt-2 space-y-2 text-[11px] leading-relaxed text-muted-foreground">
              <li className="flex gap-2">
                <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-medium text-primary">
                  1
                </span>
                选技能：先想清楚要「快筛」还是「深挖」。
              </li>
              <li className="flex gap-2">
                <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-medium text-primary">
                  2
                </span>
                填标的：公司名、代码、行业或一句具体问题。
              </li>
              <li className="flex gap-2">
                <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-medium text-primary">
                  3
                </span>
                看结论：所有技能共用同一套数据工具与报告存档，结论可以直接追问。
              </li>
            </ol>
          </div>

          {installed && missingCount > 0 && (
            <div className="rounded-xl border border-warning/30 bg-warning/5 p-4">
              <h2 className="text-xs font-semibold text-warning">有技能没装好</h2>
              <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                当前部署有 {missingCount} 个技能未安装或未启用，对应卡片已标注「未启用」。
              </p>
              <button
                type="button"
                onClick={() => navigate("/plugins")}
                className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
              >
                到插件页面检查
                <ArrowRight className="h-3 w-3" />
              </button>
            </div>
          )}

          <p className="px-1 text-[10px] leading-relaxed text-muted-foreground/60">
            技能库来自开源项目 ai-berkshire，已接入 TradingClaw 的数据加速层。
            所有输出仅供研究参考，不构成投资建议。
          </p>
        </aside>
      </div>

      {/* ── Skill dialog ─────────────────────────────────────────────── */}
      {active && (
        <SkillDialog
          skill={active.skill}
          subject={active.subject}
          available={available(active.skill.id)}
          launching={launching}
          dialogRef={dialogRef}
          subjectRef={subjectRef}
          onChange={(subject) => setActive({ ...active, subject })}
          onClose={() => setActive(null)}
          onLaunch={() => void launch(active.skill.id, active.subject)}
        />
      )}
    </div>
  );
}

/* ── pieces ──────────────────────────────────────────────────────────── */

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-2.5 py-1 text-[11px] transition",
        active
          ? "border-primary/40 bg-primary/10 font-medium text-primary"
          : "bg-card text-muted-foreground hover:border-border hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function SkillCard({
  skill,
  available,
  onOpen,
}: {
  skill: BerkshireSkill;
  available: boolean;
  onOpen: () => void;
}) {
  const Icon = skill.icon;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group relative flex h-full flex-col rounded-xl border bg-card p-3.5 text-left transition hover:border-primary/40 hover:shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
    >
      <div className="flex items-start gap-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <h3 className="truncate text-[13px] font-semibold">{skill.name}</h3>
            {!available && (
              <span className="shrink-0 rounded bg-muted px-1 py-0.5 text-[9px] text-muted-foreground">
                未启用
              </span>
            )}
          </div>
          <p className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground/60">
            {skill.id}
          </p>
        </div>
      </div>

      <p className="mt-2.5 text-[13px] leading-snug">{skill.purpose}</p>
      <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-muted-foreground">
        {skill.scenario}
      </p>

      <div className="mt-auto flex items-end justify-between gap-2 pt-3">
        <div className="flex min-w-0 flex-wrap gap-1">
          {skill.tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="rounded bg-muted px-1.5 py-0.5 text-[9px] text-muted-foreground"
            >
              {tag}
            </span>
          ))}
        </div>
        <span className="flex shrink-0 items-center gap-1.5 whitespace-nowrap text-[10px] text-muted-foreground/60">
          <Clock className="h-3 w-3" />
          {skill.duration}
          <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/40 transition group-hover:translate-x-0.5 group-hover:text-primary" />
        </span>
      </div>
    </button>
  );
}

function SkillDialog({
  skill,
  subject,
  available,
  launching,
  dialogRef,
  subjectRef,
  onChange,
  onClose,
  onLaunch,
}: {
  skill: BerkshireSkill;
  subject: string;
  available: boolean;
  launching: boolean;
  dialogRef: RefObject<HTMLDivElement | null>;
  subjectRef: RefObject<HTMLTextAreaElement | null>;
  onChange: (subject: string) => void;
  onClose: () => void;
  onLaunch: () => void;
}) {
  const Icon = skill.icon;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-[8vh] backdrop-blur-[2px]">
      <button
        type="button"
        aria-label="关闭"
        onClick={onClose}
        className="absolute inset-0 h-full w-full cursor-default"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="berkshire-dialog-title"
        className="relative z-10 w-full max-w-2xl rounded-2xl border bg-card shadow-xl"
      >
        <div className="flex items-start gap-3 border-b p-5">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Icon className="h-5 w-5" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 id="berkshire-dialog-title" className="text-base font-semibold">
              {skill.name}
            </h2>
            <p className="mt-0.5 font-mono text-[11px] text-muted-foreground/60">{skill.id}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-4 p-5">
          <p className="text-sm leading-relaxed">{skill.purpose}</p>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="适合场景">{skill.scenario}</Field>
            <Field label="产出">{skill.deliverable}</Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="需要你提供">{skill.needs}</Field>
            <Field label="预计耗时">{skill.duration}</Field>
          </div>

          <div>
            <div className="flex items-center justify-between">
              <label htmlFor="berkshire-subject" className="text-xs font-medium text-muted-foreground">
                要研究什么
              </label>
              <span className="text-[10px] text-muted-foreground/60">⌘/Ctrl + Enter 开始</span>
            </div>
            <textarea
              id="berkshire-subject"
              ref={subjectRef}
              value={subject}
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  onLaunch();
                }
              }}
              rows={3}
              placeholder={skill.needs}
              className="mt-1.5 w-full resize-none rounded-lg border bg-background px-3 py-2 text-sm outline-none transition placeholder:text-muted-foreground/60 focus:border-primary/60 focus:ring-2 focus:ring-primary/15"
            />
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {[skill.example, ...skill.tags.slice(0, 2)].map((sample) => (
                <button
                  key={sample}
                  type="button"
                  onClick={() => onChange(sample)}
                  className="rounded-full border bg-background px-2 py-0.5 text-[10px] text-muted-foreground transition hover:border-primary/40 hover:text-foreground"
                >
                  {sample}
                </button>
              ))}
            </div>
          </div>

          {!available && (
            <p className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2 text-[11px] text-muted-foreground">
              这个技能在当前部署里没有启用。到「插件 → Skill」里开启，或重新部署后再试。
            </p>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t p-4">
          <p className="text-[10px] leading-relaxed text-muted-foreground/70">
            会在智能体里新建会话并立即开始，可随时中断或追问。
          </p>
          <div className="flex shrink-0 gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border px-3 py-1.5 text-xs text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              取消
            </button>
            <button
              type="button"
              onClick={onLaunch}
              disabled={launching || !available || !subject.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-1.5 text-xs font-medium text-primary-foreground transition hover:opacity-90 disabled:opacity-50"
            >
              {launching ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              开始研究
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border bg-background/60 px-3 py-2">
      <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground/70">
        {label}
      </p>
      <p className="mt-0.5 text-[12px] leading-relaxed">{children}</p>
    </div>
  );
}
