import { useEffect, useState } from "react";
import {
  CalendarClock,
  CheckCircle2,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
  XCircle,
} from "lucide-react";
import { api, type DeliveryChannel, type ScheduledRunItem } from "@/lib/api";

const fieldClass =
  "w-full rounded-md border bg-background px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60";
const labelClass = "text-sm font-medium";
const hintClass = "text-xs text-muted-foreground";

export function Scheduled() {
  const [jobs, setJobs] = useState<ScheduledRunItem[]>([]);
  const [channels, setChannels] = useState<DeliveryChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [prompt, setPrompt] = useState("");
  const [schedule, setSchedule] = useState("0 9 * * 1-5");
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [jobsList, channelList] = await Promise.all([
        api.listScheduledRuns(),
        api.listAvailableDeliveryChannels(),
      ]);
      setJobs(Array.isArray(jobsList) ? jobsList : []);
      setChannels(Array.isArray(channelList) ? channelList : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function toggleChannel(name: string) {
    setSelectedChannels((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  }

  async function createJob(e: React.FormEvent) {
    e.preventDefault();
    if (!prompt.trim() || !schedule.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      await api.createScheduledRun({
        id: editingId ?? undefined,
        prompt: prompt.trim(),
        schedule: schedule.trim(),
        config: { channels: selectedChannels },
        timezone: timezone.trim() || undefined,
      });
      setPrompt("");
      setSchedule("0 9 * * 1-5");
      setTimezone("Asia/Shanghai");
      setSelectedChannels([]);
      setEditingId(null);
      await load();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : editingId ? "保存失败" : "创建失败");
    } finally {
      setCreating(false);
    }
  }

  function startEdit(job: ScheduledRunItem) {
    const ch = jobChannels(job);
    setEditingId(job.id);
    setPrompt(job.prompt);
    setSchedule(job.schedule);
    setTimezone(job.timezone || "Asia/Shanghai");
    setSelectedChannels(ch);
    setCreateError(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function cancelEdit() {
    setEditingId(null);
    setPrompt("");
    setSchedule("0 9 * * 1-5");
    setTimezone("Asia/Shanghai");
    setSelectedChannels([]);
    setCreateError(null);
  }

  async function removeJob(id: string) {
    if (!window.confirm("确认删除该定时任务？")) return;
    try {
      await api.deleteScheduledRun(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  }

  function jobChannels(job: ScheduledRunItem): string[] {
    const cfg = job.config ?? {};
    const ch = cfg.channels;
    return Array.isArray(ch) ? ch.filter((c): c is string => typeof c === "string") : [];
  }

  function channelLabel(name: string): string {
    const found = channels.find((c) => c.name === name);
    return found?.display_name || name;
  }

  function scheduleLabel(job: ScheduledRunItem): string {
    const sch = job.schedule;
    if (/^\d+$/.test(sch)) {
      const secs = Math.round(Number(sch) / 1000);
      return `${secs} 秒间隔`;
    }
    return sch;
  }

  function statusBadge(status: string) {
    const ok = status === "completed";
    return (
      <span className="inline-flex items-center gap-1 text-xs">
        {ok ? (
          <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
        ) : (
          <XCircle className="h-3.5 w-3.5 text-muted-foreground" />
        )}
        {status}
      </span>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <CalendarClock className="h-5 w-5" />
            定时任务
          </h1>
          <p className={hintClass}>定时执行的投研任务，执行结果可投递到已选通道。</p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="inline-flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
        >
          <RefreshCw className="h-4 w-4" />
          刷新
        </button>
      </div>

      {error && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">{error}</div>}

      {/* 创建表单 */}
      <form onSubmit={(e) => void createJob(e)} className="space-y-4 rounded-lg border bg-card p-5 shadow-sm">
        <h2 className="text-sm font-semibold">
          {editingId ? "编辑定时任务" : "新建定时任务"}
          {editingId && (
            <span className="ml-2 text-xs font-normal text-muted-foreground">
              修改后将以同一 id 覆盖原任务
            </span>
          )}
        </h2>

        <div className="space-y-1.5">
          <label className={labelClass}>任务内容 (Prompt)</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            className={`${fieldClass} min-h-20 resize-y`}
            placeholder="例如：盘前扫描：按昨日异常成交量排名并总结隔夜新闻"
            required
          />
        </div>

        <div className="space-y-1.5">
          <label className={labelClass}>调度 (Schedule)</label>
          <input
            value={schedule}
            onChange={(e) => setSchedule(e.target.value)}
            className={fieldClass}
            placeholder="5 段 cron（如 0 9 * * 1-5）或毫秒间隔（如 86400000）"
          />
          <p className={hintClass}>cron 示例：工作日 09:00 = 0 9 * * 1-5；也可填整数毫秒间隔。</p>
        </div>

        <div className="space-y-1.5">
          <label className={labelClass}>时区 (Timezone)</label>
          <input
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            className={fieldClass}
            placeholder="IANA 时区键，如 Asia/Shanghai"
          />
          <p className={hintClass}>
            cron 按此时区计算。留空 = UTC。中国时区用 <code>Asia/Shanghai</code>。
          </p>
        </div>

        {channels.length > 0 && (
          <div className="space-y-1.5">
            <span className={labelClass}>投递到通道（可多选）</span>
            <div className="flex flex-wrap gap-2">
              {channels.map((ch) => {
                const checked = selectedChannels.includes(ch.name);
                return (
                  <label
                    key={ch.name}
                    className={`flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm transition ${
                      checked ? "border-primary bg-primary/10" : "hover:bg-muted"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleChannel(ch.name)}
                      className="h-4 w-4"
                    />
                    {ch.display_name || ch.name}
                  </label>
                );
              })}
            </div>
            <p className={hintClass}>不选则结果只保存在 Web UI（会话/运行记录）。</p>
          </div>
        )}

        {createError && <div className="text-sm text-red-600">{createError}</div>}

        <div className="flex items-center justify-end gap-2">
          {editingId && (
            <button
              type="button"
              onClick={cancelEdit}
              className="inline-flex items-center justify-center gap-2 rounded-md border px-4 py-2 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              取消编辑
            </button>
          )}
          <button
            type="submit"
            disabled={creating || !prompt.trim() || !schedule.trim()}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {creating ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : editingId ? (
              <Pencil className="h-4 w-4" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            {editingId ? "保存修改" : "创建任务"}
          </button>
        </div>
      </form>

      {/* 任务列表 */}
      <div className="space-y-2">
        <h2 className="text-sm font-semibold">已有任务</h2>
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-8 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            加载中…
          </div>
        ) : jobs.length === 0 ? (
          <div className="rounded-lg border bg-card p-8 text-center text-sm text-muted-foreground">
            暂无定时任务
          </div>
        ) : (
          jobs.map((job) => (
            <div key={job.id} className="rounded-lg border bg-card p-4 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{job.prompt}</p>
                  <p className={`${hintClass} mt-1`}>
                    {scheduleLabel(job)} · 下次执行：{new Date(job.next_run_at).toLocaleString()}
                  </p>
                  {jobChannels(job).length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {jobChannels(job).map((name) => (
                        <span
                          key={name}
                          className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary"
                        >
                          {channelLabel(name)}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className={`${hintClass} mt-2`}>未设置投递通道（结果仅存 Web UI）</p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {statusBadge(job.status)}
                  <button
                    type="button"
                    onClick={() => startEdit(job)}
                    title="编辑"
                    className="inline-flex items-center justify-center rounded-md p-2 text-muted-foreground transition hover:bg-muted hover:text-foreground"
                  >
                    <Pencil className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void removeJob(job.id)}
                    title="删除"
                    className="inline-flex items-center justify-center rounded-md p-2 text-muted-foreground transition hover:bg-red-50 hover:text-red-600"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
