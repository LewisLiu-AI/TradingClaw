import { useEffect, useId, useState, type FormEvent } from "react";
import { Gauge, KeyRound, Loader2, RefreshCw, Save, User } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { api, type JuliLangProxySettings, type JuliLangProxyStatus } from "@/lib/api";

const fieldClass =
  "w-full rounded-md border bg-background px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60";
const labelClass = "text-sm font-medium";
const hintClass = "text-xs text-muted-foreground";

const STATUS_POLL_INTERVAL_MS = 30_000;

interface FormState {
  enabled: boolean;
  trade_no: string;
  api_key: string;
  username: string;
  password: string;
  quota_alert_threshold: number;
}

function formFromSettings(settings: JuliLangProxySettings): FormState {
  return {
    enabled: settings.enabled,
    trade_no: "",
    api_key: "",
    username: settings.username || "",
    password: "",
    quota_alert_threshold: settings.quota_alert_threshold || 1000,
  };
}

function formatEpoch(epoch: number | null): string {
  if (!epoch) return "—";
  return new Date(epoch * 1000).toLocaleString();
}

export function JuLiangProxySettings() {
  const { t } = useTranslation();
  const idPrefix = useId();
  const [settings, setSettings] = useState<JuliLangProxySettings | null>(null);
  const [status, setStatus] = useState<JuliLangProxyStatus | null>(null);
  const [form, setForm] = useState<FormState>({
    enabled: false,
    trade_no: "",
    api_key: "",
    username: "",
    password: "",
    quota_alert_threshold: 1000,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;

    Promise.all([api.getJuliangProxySettings(), api.getJuliangProxyStatus()])
      .then(([nextSettings, nextStatus]) => {
        if (!alive) return;
        setSettings(nextSettings);
        setForm(formFromSettings(nextSettings));
        setStatus(nextStatus);
      })
      .catch((loadError) => {
        if (!alive) return;
        setError(loadError instanceof Error ? loadError.message : t("juliangProxy.loadFailed"));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    const interval = window.setInterval(() => {
      api
        .getJuliangProxyStatus()
        .then((nextStatus) => {
          if (alive) setStatus(nextStatus);
        })
        .catch(() => {
          /* silent — transient poll failure */
        });
    }, STATUS_POLL_INTERVAL_MS);

    return () => {
      alive = false;
      window.clearInterval(interval);
    };
  }, [t]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload: {
        enabled: boolean;
        trade_no?: string;
        api_key?: string;
        username?: string;
        password?: string;
        quota_alert_threshold: number;
      } = {
        enabled: form.enabled,
        quota_alert_threshold: Number(form.quota_alert_threshold) || 1000,
      };
      if (form.trade_no.trim()) payload.trade_no = form.trade_no.trim();
      if (form.api_key.trim()) payload.api_key = form.api_key.trim();
      if (form.username.trim()) payload.username = form.username.trim();
      if (form.password.trim()) payload.password = form.password.trim();

      const nextSettings = await api.updateJuliangProxySettings(payload);
      setSettings(nextSettings);
      setForm(formFromSettings(nextSettings));
      toast.success(t("juliangProxy.saved"));
      const nextStatus = await api.getJuliangProxyStatus();
      setStatus(nextStatus);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : t("juliangProxy.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const refresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      const nextStatus = await api.refreshJuliangProxy();
      setStatus(nextStatus);
      toast.success(t("juliangProxy.refreshed"));
    } catch (refreshError) {
      setError(refreshError instanceof Error ? refreshError.message : t("juliangProxy.refreshFailed"));
    } finally {
      setRefreshing(false);
    }
  };

  const surplus = status?.surplus_quantity ?? null;
  const proxyLabel = status?.current_proxy || "—";

  return (
    <section className="rounded-lg border bg-card p-5 shadow-sm">
      <div className="mb-5 flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Gauge className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">{t("juliangProxy.title")}</h2>
          </div>
          <p className="max-w-3xl text-sm text-muted-foreground">{t("juliangProxy.subtitle")}</p>
        </div>
      </div>

      {error ? (
        <div className="mb-4 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <span className="font-medium">{t("juliangProxy.errorPrefix")}: </span>
          <span>{error}</span>
        </div>
      ) : null}

      <form onSubmit={submit} className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(280px,0.9fr)]">
        <div className="grid gap-4">
          <label className="flex items-center justify-between gap-3 rounded-md border bg-muted/20 px-3 py-2">
            <span className={labelClass}>{t("juliangProxy.enabled")}</span>
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(event) => setForm({ ...form, enabled: event.target.checked })}
              className="h-4 w-4 accent-primary"
              disabled={loading}
            />
          </label>

          <label className="grid gap-2" htmlFor={`${idPrefix}-trade-no`}>
            <span className={labelClass}>{t("juliangProxy.tradeNo")}</span>
            <input
              id={`${idPrefix}-trade-no`}
              value={form.trade_no}
              onChange={(event) => setForm({ ...form, trade_no: event.target.value })}
              className={fieldClass}
              placeholder={
                settings?.trade_no_configured ? t("juliangProxy.configured") : "2047476805247018"
              }
              autoComplete="off"
              disabled={loading}
            />
          </label>

          <label className="grid gap-2" htmlFor={`${idPrefix}-api-key`}>
            <span className={labelClass}>{t("juliangProxy.apiKey")}</span>
            <div className="relative">
              <KeyRound className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <input
                id={`${idPrefix}-api-key`}
                type="password"
                value={form.api_key}
                onChange={(event) => setForm({ ...form, api_key: event.target.value })}
                className={`${fieldClass} pl-9`}
                placeholder={
                  settings?.api_key_configured ? t("juliangProxy.configured") : ""
                }
                autoComplete="new-password"
                disabled={loading}
              />
            </div>
          </label>

          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-2" htmlFor={`${idPrefix}-username`}>
              <span className={labelClass}>{t("juliangProxy.username")}</span>
              <div className="relative">
                <User className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                  id={`${idPrefix}-username`}
                  value={form.username}
                  onChange={(event) => setForm({ ...form, username: event.target.value })}
                  className={`${fieldClass} pl-9`}
                  placeholder={
                    settings?.username ? settings.username : t("juliangProxy.usernamePlaceholder")
                  }
                  autoComplete="off"
                  disabled={loading}
                />
              </div>
            </label>

            <label className="grid gap-2" htmlFor={`${idPrefix}-password`}>
              <span className={labelClass}>{t("juliangProxy.password")}</span>
              <input
                id={`${idPrefix}-password`}
                type="password"
                value={form.password}
                onChange={(event) => setForm({ ...form, password: event.target.value })}
                className={fieldClass}
                placeholder={
                  settings?.password_configured ? t("juliangProxy.configured") : ""
                }
                autoComplete="new-password"
                disabled={loading}
              />
            </label>
          </div>

          <label className="grid gap-2" htmlFor={`${idPrefix}-threshold`}>
            <span className={labelClass}>{t("juliangProxy.threshold")}</span>
            <input
              id={`${idPrefix}-threshold`}
              type="number"
              min={1}
              step={100}
              value={form.quota_alert_threshold}
              onChange={(event) =>
                setForm({ ...form, quota_alert_threshold: Number(event.target.value) })
              }
              className={fieldClass}
              disabled={loading}
            />
            <span className={hintClass}>{t("juliangProxy.thresholdHint")}</span>
          </label>

          <button
            type="submit"
            disabled={loading || saving}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {t("juliangProxy.save")}
          </button>
        </div>

        <div className="grid gap-4">
          <div className="rounded-md border bg-muted/20 p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <span className="text-sm font-medium">{t("juliangProxy.surplus")}</span>
              {loading ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : null}
            </div>
            <div className="text-2xl font-semibold">
              {surplus !== null ? surplus.toLocaleString() : t("juliangProxy.notConfigured")}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {t("juliangProxy.surplusHint")} {status?.quota_alert_threshold ?? 1000}
            </p>
            {status?.last_error ? (
              <p className="mt-2 text-xs text-destructive">{status.last_error}</p>
            ) : null}
          </div>

          <div className="rounded-md border bg-muted/20 p-4">
            <div className="mb-3 text-sm font-medium">{t("juliangProxy.currentProxy")}</div>
            <div className="break-all font-mono text-sm">{proxyLabel}</div>
            <div className="mt-2 space-y-1 text-xs text-muted-foreground">
              <div>
                {t("juliangProxy.proxyStatus")}:{" "}
                {status ? (
                  <span className={status.proxy_valid ? "text-emerald-600" : "text-muted-foreground"}>
                    {status.proxy_valid
                      ? t("juliangProxy.proxyValid")
                      : t("juliangProxy.proxyInvalid")}
                  </span>
                ) : (
                  "—"
                )}
              </div>
              <div>
                {t("juliangProxy.lastExtracted")}: {formatEpoch(status?.last_extracted_at ?? null)}
              </div>
            </div>
          </div>

          <button
            type="button"
            onClick={refresh}
            disabled={loading || refreshing || !status?.configured}
            className="inline-flex items-center justify-center gap-2 rounded-md border px-4 py-2 text-sm transition hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
          >
            {refreshing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            {t("juliangProxy.refresh")}
          </button>
          <p className="text-xs text-muted-foreground">{t("juliangProxy.refreshHint")}</p>
        </div>
      </form>
    </section>
  );
}
