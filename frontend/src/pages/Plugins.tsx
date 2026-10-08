import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Blocks, Loader2, Plug, RefreshCw, Search, Settings, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api, type MCPServerInfo, type PluginsResponse, type SkillInfo } from "@/lib/api";
import { cn } from "@/lib/utils";

type TabKey = "mcp" | "skill";

interface ServerFormState {
  type: string;
  command: string;
  args: string;
  url: string;
  tool_timeout: string;
  init_timeout: string;
  enabled_tools: string;
}

function toFormState(server: MCPServerInfo): ServerFormState {
  return {
    type: ["stdio", "sse", "streamableHttp"].includes(server.transport) ? server.transport : "",
    command: server.command,
    args: server.args.join(" "),
    url: server.url,
    tool_timeout: String(server.tool_timeout),
    init_timeout: server.init_timeout === null ? "" : String(server.init_timeout),
    enabled_tools: server.enabled_tools.join(", "),
  };
}

function Toggle({
  checked,
  disabled,
  onChange,
  label,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-60",
        checked ? "bg-primary" : "bg-muted-foreground/30"
      )}
    >
      <span
        className={cn(
          "inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-[22px]" : "translate-x-0.5"
        )}
      />
    </button>
  );
}

export function Plugins() {
  const { t } = useTranslation();
  const [data, setData] = useState<PluginsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("mcp");
  const [query, setQuery] = useState("");
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [settingsServer, setSettingsServer] = useState<MCPServerInfo | null>(null);

  const load = (mode: "initial" | "refresh" = "refresh") => {
    if (mode === "initial") setLoading(true);
    else setRefreshing(true);
    setError(null);
    api
      .listPlugins()
      .then((payload) => setData(payload))
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
  };

  useEffect(() => {
    load("initial");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const mcpServers = data?.mcp ?? [];
  const skills = data?.skills ?? [];

  const filteredMcp = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return mcpServers;
    return mcpServers.filter((server) => server.name.toLowerCase().includes(needle));
  }, [mcpServers, query]);

  const filteredSkills = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return skills;
    return skills.filter((skill) =>
      `${skill.name} ${skill.description} ${skill.category}`.toLowerCase().includes(needle)
    );
  }, [skills, query]);

  const toggleMcp = (server: MCPServerInfo, next: boolean) => {
    setPendingKey(`mcp:${server.name}`);
    api
      .updateMCPServer(server.name, { enabled: next })
      .then((updated) => {
        setData((prev) =>
          prev ? { ...prev, mcp: prev.mcp.map((item) => (item.name === server.name ? updated : item)) } : prev
        );
        toast.success(next ? t("plugins.enabledToast", { name: server.name }) : t("plugins.disabledToast", { name: server.name }));
      })
      .catch((err) => {
        toast.error(`${t("plugins.saveFailed")}: ${err instanceof Error ? err.message : "Unknown error"}`);
      })
      .finally(() => setPendingKey(null));
  };

  const toggleSkill = (skill: SkillInfo, next: boolean) => {
    setPendingKey(`skill:${skill.name}`);
    api
      .updateSkillEnabled(skill.name, next)
      .then(() => {
        setData((prev) =>
          prev ? { ...prev, skills: prev.skills.map((item) => (item.name === skill.name ? { ...item, enabled: next } : item)) } : prev
        );
        toast.success(next ? t("plugins.enabledToast", { name: skill.name }) : t("plugins.disabledToast", { name: skill.name }));
      })
      .catch((err) => {
        toast.error(`${t("plugins.saveFailed")}: ${err instanceof Error ? err.message : "Unknown error"}`);
      })
      .finally(() => setPendingKey(null));
  };

  const onSettingsSaved = (updated: MCPServerInfo) => {
    setData((prev) =>
      prev ? { ...prev, mcp: prev.mcp.map((item) => (item.name === updated.name ? updated : item)) } : prev
    );
    setSettingsServer(null);
  };

  const userSkills = filteredSkills.filter((skill) => skill.source === "user");
  const bundledSkills = filteredSkills.filter((skill) => skill.source === "bundled");

  return (
    <div className="min-h-screen p-6 lg:p-8">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
        {/* Header */}
        <section className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-1">
            <h1 className="text-3xl font-bold tracking-tight">{t("plugins.title")}</h1>
            <p className="text-sm text-muted-foreground">{t("plugins.subtitle")}</p>
          </div>
          <button
            type="button"
            onClick={() => load("refresh")}
            disabled={refreshing}
            className="inline-flex items-center justify-center gap-2 self-start rounded-md border px-3 py-2 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
          >
            {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {t("plugins.refresh")}
          </button>
        </section>

        {/* Tabs + search */}
        <section className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-1" role="tablist">
            <TabButton active={tab === "mcp"} onClick={() => setTab("mcp")} icon={Plug} label={t("plugins.tabMcp")} count={mcpServers.length} />
            <TabButton active={tab === "skill"} onClick={() => setTab("skill")} icon={Sparkles} label={t("plugins.tabSkills")} count={skills.length} />
          </div>
          <div className="relative w-full md:w-72">
            <Search className="pointer-events-none absolute start-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={tab === "mcp" ? t("plugins.searchMcp") : t("plugins.searchSkills")}
              className="w-full rounded-md border bg-background ps-9 pe-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
            />
          </div>
        </section>

        {/* Content */}
        {loading ? (
          <div className="flex min-h-40 items-center justify-center rounded-lg border bg-card text-sm text-muted-foreground">
            <Loader2 className="me-2 h-4 w-4 animate-spin" />
            {t("plugins.loading")}
          </div>
        ) : error ? (
          <div className="rounded-lg border bg-card p-6 text-center text-sm">
            <div className="font-medium text-foreground">{t("plugins.loadFailed")}</div>
            <div className="mt-1 text-muted-foreground">{error}</div>
          </div>
        ) : tab === "mcp" ? (
          <McpTab
            servers={filteredMcp}
            totalCount={mcpServers.length}
            configPath={data?.config_path ?? ""}
            pendingKey={pendingKey}
            onToggle={toggleMcp}
            onOpenSettings={setSettingsServer}
          />
        ) : (
          <SkillsTab
            userSkills={userSkills}
            bundledSkills={bundledSkills}
            totalCount={skills.length}
            pendingKey={pendingKey}
            onToggle={toggleSkill}
          />
        )}
      </div>

      {settingsServer && (
        <ServerSettingsDialog
          server={settingsServer}
          configPath={data?.config_path ?? ""}
          onClose={() => setSettingsServer(null)}
          onSaved={onSettingsSaved}
        />
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  icon: Icon,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof Plug;
  label: string;
  count: number;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-sm transition-colors",
        active ? "bg-muted font-medium text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
      )}
    >
      <Icon className="h-4 w-4" />
      {label}
      <span className={cn("text-xs", active ? "text-muted-foreground" : "text-muted-foreground/70")}>{count}</span>
    </button>
  );
}

function McpTab({
  servers,
  totalCount,
  configPath,
  pendingKey,
  onToggle,
  onOpenSettings,
}: {
  servers: MCPServerInfo[];
  totalCount: number;
  configPath: string;
  pendingKey: string | null;
  onToggle: (server: MCPServerInfo, next: boolean) => void;
  onOpenSettings: (server: MCPServerInfo) => void;
}) {
  const { t } = useTranslation();
  if (totalCount === 0) {
    return (
      <div className="rounded-lg border bg-card p-8 text-center">
        <Plug className="mx-auto h-8 w-8 text-muted-foreground/50" />
        <div className="mt-3 font-medium">{t("plugins.mcpEmpty")}</div>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{t("plugins.mcpEmptyHint")}</p>
        {configPath && (
          <p className="mx-auto mt-3 max-w-md break-all rounded-md border bg-muted/30 px-3 py-2 font-mono text-xs text-muted-foreground">
            {configPath}
          </p>
        )}
      </div>
    );
  }
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-foreground">{t("plugins.serversSection")}</h2>
      {servers.length === 0 ? (
        <div className="rounded-lg border bg-card p-6 text-center text-sm text-muted-foreground">{t("plugins.noSearchResults")}</div>
      ) : (
        <div className="divide-y overflow-hidden rounded-xl border bg-card shadow-sm">
          {servers.map((server) => (
            <div key={server.name} className="flex items-center gap-3 px-5 py-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold">{server.name}</span>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{server.transport}</span>
                  {!server.valid && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-warning/10 px-2 py-0.5 text-[11px] text-warning">
                      <AlertTriangle className="h-3 w-3" />
                      {t("plugins.invalidConfig")}
                    </span>
                  )}
                </div>
                {!server.valid && server.error && (
                  <p className="mt-1 truncate text-xs text-muted-foreground" title={server.error}>{server.error}</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => onOpenSettings(server)}
                className="rounded-md p-1.5 text-muted-foreground transition hover:bg-muted hover:text-foreground"
                title={t("plugins.settings")}
                aria-label={`${t("plugins.settings")} ${server.name}`}
              >
                <Settings className="h-4 w-4" />
              </button>
              <Toggle
                checked={server.enabled}
                disabled={pendingKey === `mcp:${server.name}`}
                onChange={(next) => onToggle(server, next)}
                label={`${server.name}: ${t("plugins.toggle")}`}
              />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function SkillsTab({
  userSkills,
  bundledSkills,
  totalCount,
  pendingKey,
  onToggle,
}: {
  userSkills: SkillInfo[];
  bundledSkills: SkillInfo[];
  totalCount: number;
  pendingKey: string | null;
  onToggle: (skill: SkillInfo, next: boolean) => void;
}) {
  const { t } = useTranslation();
  if (totalCount === 0) {
    return (
      <div className="rounded-lg border bg-card p-8 text-center">
        <Sparkles className="mx-auto h-8 w-8 text-muted-foreground/50" />
        <div className="mt-3 font-medium">{t("plugins.skillsEmpty")}</div>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{t("plugins.skillsEmptyHint")}</p>
      </div>
    );
  }

  const renderGroup = (title: string, list: SkillInfo[]) => {
    if (list.length === 0) return null;
    return (
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        <div className="divide-y overflow-hidden rounded-xl border bg-card shadow-sm">
          {list.map((skill) => (
            <div key={`${skill.source}:${skill.name}`} className="flex items-center gap-3 px-5 py-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-sm font-semibold">{skill.name}</span>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">{skill.category}</span>
                </div>
                {skill.description && (
                  <p className="mt-1 line-clamp-2 text-xs text-muted-foreground" title={skill.description}>{skill.description}</p>
                )}
              </div>
              <Toggle
                checked={skill.enabled}
                disabled={pendingKey === `skill:${skill.name}`}
                onChange={(next) => onToggle(skill, next)}
                label={`${skill.name}: ${t("plugins.toggle")}`}
              />
            </div>
          ))}
        </div>
      </section>
    );
  };

  return (
    <div className="space-y-6">
      {renderGroup(t("plugins.userSkillsSection"), userSkills)}
      {renderGroup(t("plugins.bundledSkillsSection"), bundledSkills)}
    </div>
  );
}

function ServerSettingsDialog({
  server,
  configPath,
  onClose,
  onSaved,
}: {
  server: MCPServerInfo;
  configPath: string;
  onClose: () => void;
  onSaved: (server: MCPServerInfo) => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState(() => toFormState(server));
  const [saving, setSaving] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    try {
      const trimmedType = form.type.trim();
      const initTimeoutRaw = form.init_timeout.trim();
      const updated = await api.updateMCPServer(server.name, {
        type: trimmedType === "" ? null : (trimmedType as "stdio" | "sse" | "streamableHttp"),
        command: form.command.trim(),
        args: form.args.trim() ? form.args.trim().split(/\s+/) : [],
        url: form.url.trim(),
        tool_timeout: Number(form.tool_timeout) || 30,
        init_timeout: initTimeoutRaw === "" ? null : Number(initTimeoutRaw),
        enabled_tools: form.enabled_tools
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      });
      toast.success(t("plugins.savedToast", { name: server.name }));
      onSaved(updated);
    } catch (err) {
      toast.error(`${t("plugins.saveFailed")}: ${err instanceof Error ? err.message : "Unknown error"}`);
    } finally {
      setSaving(false);
    }
  };

  const fieldClass =
    "w-full rounded-md border bg-background px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20";
  const labelClass = "text-sm font-medium";
  const hintClass = "text-xs text-muted-foreground";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={`${t("plugins.dialogTitle")}: ${server.name}`}>
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <form
        onSubmit={submit}
        className="relative z-10 flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-xl border bg-card shadow-lg"
      >
        <div className="flex items-center justify-between border-b px-5 py-4">
          <div className="flex items-center gap-2">
            <Blocks className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{t("plugins.dialogTitle")}</h2>
          </div>
          <span className="truncate text-sm font-mono text-muted-foreground">{server.name}</span>
        </div>

        <div className="grid gap-4 overflow-auto px-5 py-4">
          <label className="grid gap-2">
            <span className={labelClass}>{t("plugins.type")}</span>
            <select value={form.type} onChange={(event) => setForm({ ...form, type: event.target.value })} className={fieldClass}>
              <option value="">{t("plugins.transportAuto")}</option>
              <option value="stdio">stdio</option>
              <option value="sse">sse</option>
              <option value="streamableHttp">streamableHttp</option>
            </select>
          </label>

          <label className="grid gap-2">
            <span className={labelClass}>{t("plugins.command")}</span>
            <input value={form.command} onChange={(event) => setForm({ ...form, command: event.target.value })} className={fieldClass} placeholder="uvx / npx / ..." />
          </label>

          <label className="grid gap-2">
            <span className={labelClass}>{t("plugins.args")}</span>
            <input value={form.args} onChange={(event) => setForm({ ...form, args: event.target.value })} className={fieldClass} placeholder={t("plugins.argsHint")} />
          </label>

          <label className="grid gap-2">
            <span className={labelClass}>URL</span>
            <input value={form.url} onChange={(event) => setForm({ ...form, url: event.target.value })} className={fieldClass} placeholder="https://..." />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-2">
              <span className={labelClass}>{t("plugins.toolTimeout")}</span>
              <input type="number" min={0.1} step={0.1} value={form.tool_timeout} onChange={(event) => setForm({ ...form, tool_timeout: event.target.value })} className={fieldClass} />
            </label>
            <label className="grid gap-2">
              <span className={labelClass}>{t("plugins.initTimeout")}</span>
              <input type="number" min={0.1} step={0.1} value={form.init_timeout} onChange={(event) => setForm({ ...form, init_timeout: event.target.value })} className={fieldClass} placeholder={t("plugins.initTimeoutHint")} />
            </label>
          </div>

          <label className="grid gap-2">
            <span className={labelClass}>{t("plugins.enabledTools")}</span>
            <input value={form.enabled_tools} onChange={(event) => setForm({ ...form, enabled_tools: event.target.value })} className={fieldClass} placeholder="*" />
            <span className={hintClass}>{t("plugins.enabledToolsHint")}</span>
          </label>

          {(server.env_keys.length > 0 || server.header_keys.length > 0 || server.has_auth) && (
            <div className="rounded-md border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
              {server.env_keys.length > 0 && (
                <p className="truncate">
                  {t("plugins.envKeys")}: <span className="font-mono">{server.env_keys.join(", ")}</span>
                </p>
              )}
              {server.header_keys.length > 0 && (
                <p className="truncate">
                  {t("plugins.headerKeys")}: <span className="font-mono">{server.header_keys.join(", ")}</span>
                </p>
              )}
              {server.has_auth && <p>{t("plugins.auth")}: OAuth</p>}
              <p className="mt-1 opacity-80">{t("plugins.secretsNote")}</p>
            </div>
          )}

          {configPath && (
            <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{t("plugins.configPath")}: </span>
              <span className="break-all font-mono">{configPath}</span>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t px-5 py-3">
          <button type="button" onClick={onClose} className="rounded-md border px-3 py-2 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground">
            {t("plugins.cancel")}
          </button>
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            {saving ? t("plugins.saving") : t("plugins.save")}
          </button>
        </div>
      </form>
    </div>
  );
}
