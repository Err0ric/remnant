import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { Command, PageHeader } from "@/components/shell/PageHeader";
import { FormError } from "@/features/auth/FormError";
import { since, stamp } from "@/features/overview/time";
import { ApiError, api, type Source, type WatchedDevice } from "@/lib/api";
import { navigate, useSectionTab, type PageId } from "@/lib/route";
import { useAttention } from "@/features/dashboard/attention";
import { lag } from "./flow";
import { SourceFlow } from "./SourceFlow";
import { StatusLine } from "./StatusLine";
import { SystemStrip, type SourceTally } from "./SystemStrip";

type Level = "unhealthy" | "attention" | "paused" | "healthy";
type TabId = "sources" | "enrichment" | "agents" | "devices" | "alerts";

interface Row {
  key: string;
  name: string;
  /** A second line in monospace: an id, an address, a machine. */
  sub?: string;
  /** What it is or how it is read, in plain words. */
  detail?: string;
  last: string | null;
  level: Level;
  reason?: string | null;
  page?: PageId;
  hourly?: number[];
  device?: WatchedDevice;
  /** Status in a word when the level alone would not say why (F55). */
  word?: string;
}

const LEVELS: { id: Level; label: string; color: string }[] = [
  { id: "unhealthy", label: "Unhealthy", color: "border-t-danger text-danger" },
  { id: "attention", label: "Needs attention", color: "border-t-warn text-warn" },
  { id: "paused", label: "Paused", color: "border-t-border-strong text-text-secondary" },
  { id: "healthy", label: "Healthy", color: "border-t-ok text-ok" },
];
const BADGE: Record<Level, string> = {
  unhealthy: "bg-sev-critical-bg text-sev-critical-text",
  attention: "bg-sev-medium-bg text-sev-medium-text",
  paused: "bg-sev-info-bg text-sev-info-text",
  healthy: "bg-local-bg text-local-text",
};
const TABS: { id: TabId; label: string }[] = [
  { id: "sources", label: "Sources" },
  { id: "enrichment", label: "Enrichment feeds" },
  { id: "agents", label: "Endpoint agents" },
  { id: "devices", label: "Watched devices" },
  { id: "alerts", label: "Alerts and schedules" },
];
const TAB_IDS = TABS.map((t) => t.id);
const SILENCE = [
  { s: 300, label: "5 minutes" },
  { s: 900, label: "15 minutes" },
  { s: 3600, label: "1 hour" },
  { s: 4 * 3600, label: "4 hours" },
  { s: 86400, label: "24 hours" },
];
const KIND_LABEL: Record<string, string> = {
  file: "Files",
  loki: "Grafana Loki",
  otlp: "OpenTelemetry receiver",
  m365: "Microsoft 365",
  anthropic: "Anthropic admin API",
  syslog: "Syslog listener",
};

/** "daily", "every 6 hours": a feed's own update interval. */
function every(seconds: number): string {
  if (seconds >= 86400 && seconds % 86400 === 0)
    return seconds === 86400 ? "daily" : `every ${seconds / 86400} days`;
  if (seconds >= 3600)
    return seconds === 3600 ? "hourly" : `every ${Math.round(seconds / 3600)} hours`;
  return `every ${Math.max(1, Math.round(seconds / 60))} minutes`;
}

function human(seconds: number): string {
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h`;
  return `${Math.round(seconds / 86400)} d`;
}

function sourceRow(s: Source): Row {
  const st = s.status;
  const kind = s.kind ?? "file";
  const base: Row = {
    key: s.source_id,
    name: s.source_id,
    detail: KIND_LABEL[kind] ?? kind,
    last: st.last_event_at,
    level: "healthy",
    page: "sources",
  };
  if (!s.enabled || st.state === "disabled")
    return { ...base, level: "paused", reason: "Turned off" };
  if (st.state === "error") return { ...base, level: "unhealthy", reason: st.error };
  if (s.quiet?.state === "quiet")
    return {
      ...base,
      level: "unhealthy",
      reason: `No events for over ${human(s.quiet.quiet_after_s)}`,
    };
  if (st.warnings?.length) return { ...base, level: "attention", reason: st.warnings.join("; ") };
  if (st.retry_at)
    return { ...base, level: "attention", reason: `Retrying at ${stamp(st.retry_at)} UTC` };
  if (st.time_offset_text) return { ...base, level: "attention", reason: st.time_offset_text };
  if ((st.behind_s ?? 0) > 3600)
    return { ...base, level: "attention", reason: `Reading is ${human(st.behind_s ?? 0)} behind` };
  if (st.records_skipped)
    return {
      ...base,
      level: "attention",
      reason: `${st.records_skipped} records could not be read`,
    };
  if (st.files_waiting)
    return { ...base, level: "attention", reason: `${st.files_waiting} files still being written` };
  if (st.state === "waiting") return { ...base, level: "attention", reason: "Not read yet" };
  return base;
}

function Spark({ counts }: { counts: number[] }) {
  const top = Math.max(1, ...counts);
  return (
    <span className="flex h-4 items-end gap-px" aria-hidden="true">
      {counts.map((n, i) => (
        <span
          key={i}
          className={`w-1 rounded-sm ${n ? "bg-accent-text opacity-80" : "bg-danger"}`}
          style={{ height: n ? `${Math.max(15, (n / top) * 100)}%` : "2px" }}
        />
      ))}
    </span>
  );
}

interface HealthPageProps {
  isAdmin: boolean;
}

/** Health (ADR-0019): is every source, connector, agent, watched device, alert target,
 * and schedule working, on one page. */
export function HealthPage({ isAdmin }: HealthPageProps) {
  const client = useQueryClient();
  const [tab, setTab] = useSectionTab<TabId>(TAB_IDS);
  const [filter, setFilter] = useState<Level | null>(null);
  const [adding, setAdding] = useState(false);
  const sources = useQuery({ queryKey: ["source-list"], queryFn: api.sources });
  const checks = useQuery({
    queryKey: ["health-checks"],
    queryFn: api.healthChecks,
    refetchInterval: 60_000,
  });
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: api.schedules });
  // Flow, gaps, totals, detections, and delivery (F55; the former Overview's numbers).
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 60_000,
  });
  const attention = useAttention();
  const enrichment = useQuery({ queryKey: ["enrichment"], queryFn: api.enrichment });
  const targets = useQuery({
    queryKey: ["alert-targets"],
    queryFn: api.alertTargets,
    enabled: isAdmin,
  });
  const remove = useMutation({
    mutationFn: api.removeWatchedDevice,
    onSuccess: () => client.invalidateQueries({ queryKey: ["health-checks"] }),
  });

  const now = new Date().toISOString();
  const list = sources.data ?? [];
  // A source that is read without errors but sent nothing in 24 hours is not flowing (F55).
  // So does one with a gap: the gap is written out under its row.
  const totals = new Map((overview.data?.volume ?? []).map((v) => [v.source_id, v.total]));
  const gapped = new Set(
    (overview.data?.volume ?? []).filter((v) => v.gaps.length).map((v) => v.source_id),
  );
  const flowing = (r: Row): Row => {
    if (!overview.data || r.level !== "healthy") return r;
    if (!totals.get(r.key)) return { ...r, level: "attention", word: "No events in 24 hours" };
    if (gapped.has(r.key)) return { ...r, level: "attention", word: "Gap" };
    return r;
  };
  const rows: Record<TabId, Row[]> = {
    sources: [
      ...((checks.data?.quarantined_files ?? 0) > 0
        ? [
            {
              key: "lake-quarantine",
              name: "Data folder",
              detail: "Stored events",
              last: null,
              level: "attention" as Level,
              reason: `${checks.data?.quarantined_files ?? 0} damaged files moved to data/quarantine (after a crash or a disk fault); searches skip them`,
            },
          ]
        : []),
      // Anything that brings events is a source, read or pulled (F59): files, the syslog
      // listener, OpenTelemetry, Loki, Microsoft 365, the Anthropic admin API.
      ...list.map((s) => flowing(sourceRow(s))),
    ],
    // Feeds are judged by their own update interval, never against log freshness (F59).
    enrichment: [
      // Enrichment feeds, once set up (ADR-0023 row 8); a fresh install lists none.
      ...(enrichment.data?.feeds ?? [])
        .filter(
          (f) =>
            f.enabled &&
            (f.installed_at ||
              (enrichment.data?.auto_update && f.downloadable && !(f.needs_key && !f.has_key))),
        )
        .map((f): Row => ({
          key: `feed:${f.feed_id}`,
          name: f.label,
          sub: f.version ?? undefined,
          detail: `${f.provider} · updated ${every(f.check_every_s)}`,
          last: f.installed_at,
          level:
            f.level === "missing"
              ? "attention"
              : f.level === "unhealthy" || f.level === "attention"
                ? f.level
                : "healthy",
          reason:
            f.error ??
            (f.level === "missing"
              ? "Not installed yet"
              : f.level === "healthy"
                ? null
                : "Edition is getting old; check automatic updates or upload a newer file"),
          page: "enrichment",
        })),
    ],
    agents: (checks.data?.agents ?? []).map((a) => ({
      key: `${a.source_id}:${a.machine}`,
      name: a.machine,
      sub: a.source_id,
      detail: `${a.kind} · ${a.events_24h.toLocaleString()} events in 24 h`,
      last: a.last_seen,
      level: a.state === "unknown" ? "attention" : a.state,
      reason: a.reason,
    })),
    devices: (checks.data?.devices ?? []).map((d) => ({
      key: d.device_id,
      name: d.name,
      sub: d.match,
      detail: `Allowed silence ${human(d.silence_s)}`,
      last: d.last_seen,
      level: d.state === "unknown" ? "attention" : d.state,
      reason: d.reason,
      hourly: d.hourly,
      device: d,
    })),
    alerts: [
      ...(targets.data ?? []).map((t): Row => ({
        key: `t:${t.target_id}`,
        name: t.name,
        detail: `Alert target · ${t.kind}`,
        last: t.last_sent_at,
        level: t.failing ? "unhealthy" : "healthy",
        reason: t.failing
          ? `${t.consecutive_failures} deliveries failed${t.last_error ? `: ${t.last_error}` : ""}`
          : null,
        page: "alerts",
      })),
      ...(schedules.data ?? []).map((s): Row => ({
        key: `s:${s.schedule_id}`,
        name: s.name,
        detail: `Schedule · ${s.kind === "rule" ? "detection rule" : "saved search"}`,
        last: s.last_run_at,
        level: s.paused ? "paused" : "healthy",
        reason: s.paused ? (s.paused_reason ?? "Paused") : null,
        page: "schedules",
      })),
    ],
  };
  const o = overview.data;
  const gapsOf = new Map((o?.volume ?? []).map((v) => [v.source_id, v.gaps.length]));
  const lastOf = new Map((o?.sources ?? []).map((s) => [s.source_id, s.last_event_at]));
  const sourceRows = rows.sources.filter((r) => r.key !== "lake-quarantine");
  const enabled = list.filter((s) => s.enabled);
  const waits = enabled
    .map((s) => ({ id: s.source_id, last: lastOf.get(s.source_id) ?? s.status.last_event_at }))
    .filter((w): w is { id: string; last: string } => Boolean(w.last))
    .sort((a, b) => a.last.localeCompare(b.last));
  const worst = waits[0];
  const tally: SourceTally = {
    total: sourceRows.length,
    healthy: sourceRows.filter((r) => r.level === "healthy" && !gapsOf.get(r.key)).length,
    gaps: list.reduce((n, s) => n + (gapsOf.get(s.source_id) ?? 0), 0),
    worstLag: worst ? lag(worst.last, now) : null,
    worstLagSource: worst?.id ?? null,
  };
  const count = (l: Level) => rows[tab].filter((r) => r.level === l).length;
  const shown = rows[tab].filter((r) => !filter || r.level === filter);
  const loading = sources.isLoading || checks.isLoading;
  const error = sources.error ?? checks.error;

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        crumbs={["Home", "System", "Health"]}
        title="Health"
        commands={
          <Command
            label={checks.isFetching || sources.isFetching ? "Refreshing…" : "Refresh"}
            onClick={() => {
              void sources.refetch();
              void checks.refetch();
              void schedules.refetch();
              if (isAdmin) void targets.refetch();
            }}
          />
        }
        meta={o ? `Updated ${since(o.generated_at, now)}` : "Checked every minute"}
      />
      <div className="flex flex-col gap-3 px-5 py-3">
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error instanceof ApiError ? error.message : "Could not load health"}
          </p>
        ) : null}
        <SystemStrip
          overview={o}
          tally={tally}
          attention={attention.items}
          isAdmin={isAdmin}
          now={now}
          onEvents={() => navigate("search")}
          onSources={() => setTab("sources")}
          onAttention={() => navigate("dashboard")}
          onDelivery={() => setTab("alerts")}
        />
        {o ? <StatusLine overview={o} now={now} /> : null}

        <div
          role="tablist"
          aria-label="Health checks"
          className="flex overflow-x-auto border-b border-border"
        >
          {TABS.map((t) => {
            const bad = rows[t.id].filter(
              (r) => r.level === "unhealthy" || r.level === "attention",
            ).length;
            return (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={tab === t.id}
                onClick={() => setTab(t.id)}
                className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm ${
                  tab === t.id
                    ? "border-accent font-semibold text-text"
                    : "border-transparent text-text-secondary hover:text-text"
                }`}
              >
                {t.label} <span className="text-text-muted">{rows[t.id].length}</span>
                {bad ? (
                  <span className="ml-1 rounded-badge bg-sev-medium-bg px-1 text-xs text-sev-medium-text">
                    {bad}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>

        <div
          role="group"
          aria-label="Show"
          className="flex flex-wrap items-center gap-1 text-sm text-text-secondary"
        >
          <span className="mr-1">Show</span>
          {[{ id: null, label: "All", color: "" }, ...LEVELS].map((l) => (
            <button
              key={l.id ?? "all"}
              type="button"
              aria-pressed={filter === l.id}
              onClick={() => setFilter(l.id as Level | null)}
              className={`rounded px-2 py-0.5 ${
                filter === l.id ? "bg-surface-head font-semibold text-text" : "hover:text-text"
              }`}
            >
              {l.label}{" "}
              <span className="font-mono tabular-nums text-text-muted">
                {loading ? "·" : l.id ? count(l.id as Level) : rows[tab].length}
              </span>
            </button>
          ))}
        </div>

        <section
          aria-label={TABS.find((t) => t.id === tab)?.label}
          className="rounded-card border border-border bg-surface"
        >
          {tab === "devices" ? (
            <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2 text-sm">
              <span className="text-text-secondary">
                Healthy while it keeps appearing in logs you already collect. {PRODUCT_NOTE}
              </span>
              {isAdmin ? (
                <button
                  type="button"
                  onClick={() => setAdding(!adding)}
                  className={`ml-auto h-8 rounded px-3 font-semibold ${
                    adding
                      ? "border border-border-strong hover:bg-surface-head"
                      : "bg-accent text-white hover:brightness-110"
                  }`}
                >
                  {adding ? "Cancel" : "Watch a device"}
                </button>
              ) : null}
            </div>
          ) : null}
          {tab === "devices" && adding && isAdmin ? (
            <DeviceForm
              targets={(targets.data ?? []).map((t) => ({ id: t.target_id, name: t.name }))}
              onDone={() => setAdding(false)}
            />
          ) : null}
          {tab === "sources" && shown.length > 0 ? (
            <SourceFlow
              overview={o}
              now={now}
              notice={shown.find((r) => r.key === "lake-quarantine")?.reason ?? null}
              sources={shown
                .filter((r) => r.key !== "lake-quarantine")
                // Problems first: errors, then gaps, then the rest that needs a look.
                .map((r, i) => ({ r, i, rank: RANK(r) }))
                .sort((a, b) => a.rank - b.rank || a.i - b.i)
                .map(({ r }) => r)
                .map((r) => ({
                  source_id: r.name,
                  level: r.level,
                  word: r.word,
                  reason: r.reason,
                  last: r.last,
                  onOpen: r.page ? () => navigate(r.page as PageId) : undefined,
                }))}
            />
          ) : shown.length === 0 ? (
            <p className="p-4 text-sm text-text-muted">
              {loading ? "Loading…" : filter ? "Nothing in this state here." : EMPTY[tab]}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" aria-label={TABS.find((t) => t.id === tab)?.label}>
                <thead>
                  <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
                    <th className="px-3 py-2 font-semibold">Name</th>
                    <th className="hidden px-3 py-2 font-semibold md:table-cell">
                      {tab === "enrichment" ? "Last updated" : "Last seen"}
                    </th>
                    {tab === "devices" ? (
                      <th className="hidden px-3 py-2 font-semibold md:table-cell">
                        Last 24 hours
                      </th>
                    ) : null}
                    <th className="hidden px-3 py-2 text-right font-semibold md:table-cell">
                      State
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => (
                    <tr key={r.key} className="border-b border-border align-top last:border-b-0">
                      <td className="min-w-0 px-3 py-2">
                        {r.page ? (
                          <button
                            type="button"
                            onClick={() => navigate(r.page as PageId)}
                            className="break-all text-left font-mono text-accent-text hover:underline"
                          >
                            {r.name}
                          </button>
                        ) : (
                          <span className={tab === "devices" ? "" : "break-all font-mono"}>
                            {r.name}
                          </span>
                        )}
                        <div className="mt-0.5 flex items-center gap-2 md:hidden">
                          <span
                            className={`rounded-badge px-1.5 py-px text-xs font-semibold ${BADGE[r.level]}`}
                          >
                            {LEVELS.find((l) => l.id === r.level)?.label}
                          </span>
                          {r.last ? (
                            <span className="font-mono text-xs text-text-secondary">
                              {since(r.last, now)}
                            </span>
                          ) : null}
                        </div>
                        {r.sub ? (
                          <div className="break-all font-mono text-xs text-text-muted">{r.sub}</div>
                        ) : null}
                        {r.detail ? (
                          <div className="text-xs text-text-muted">{r.detail}</div>
                        ) : null}
                        {r.reason ? (
                          <div
                            className={`text-xs ${r.level === "unhealthy" ? "text-danger" : "text-warn"}`}
                          >
                            {r.reason}
                          </div>
                        ) : null}
                      </td>
                      <td className="hidden whitespace-nowrap px-3 py-2 font-mono tabular-nums md:table-cell">
                        {r.last ? (
                          <span title={`${stamp(r.last)} UTC`}>{since(r.last, now)}</span>
                        ) : (
                          <span className="text-text-muted">·</span>
                        )}
                      </td>
                      {tab === "devices" ? (
                        <td className="hidden px-3 py-2 md:table-cell">
                          {r.hourly ? <Spark counts={r.hourly} /> : null}
                        </td>
                      ) : null}
                      <td className="hidden px-3 py-2 text-right md:table-cell">
                        <span
                          className={`whitespace-nowrap rounded-badge px-1.5 py-px text-xs font-semibold ${BADGE[r.level]}`}
                        >
                          {LEVELS.find((l) => l.id === r.level)?.label}
                        </span>
                        {r.device && isAdmin ? (
                          <button
                            type="button"
                            aria-label={`Stop watching ${r.device.name}`}
                            onClick={() => remove.mutate(r.key)}
                            className="mt-1 block w-full text-right text-xs text-text-secondary hover:text-danger"
                          >
                            Stop watching
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <FormError
            message={
              remove.error instanceof ApiError
                ? remove.error.message
                : remove.error
                  ? "That did not work"
                  : null
            }
          />
        </section>
      </div>
    </div>
  );
}

const PRODUCT_NOTE = "Nothing connects to the device.";

function RANK(r: Row): number {
  if (r.level === "unhealthy") return 0;
  if (r.word === "Gap") return 1;
  return { unhealthy: 0, attention: 2, paused: 3, healthy: 4 }[r.level];
}

const EMPTY: Record<TabId, ReactNode> = {
  sources:
    "No sources yet. Add files, a syslog listener, Loki, or Microsoft 365 under Settings, Sources and connectors.",
  enrichment:
    "No enrichment feeds yet: GeoIP and threat intel feeds show here once set up under Settings, Enrichment.",
  agents:
    "No agents reporting. Claude Code telemetry, endpoint agents, and the MCP inventory show one row per machine.",
  devices:
    "No watched devices. Add a network sensor, collector, or firewall by address or host name to know when it goes silent.",
  alerts: "No alert targets or schedules you can see.",
};

interface DeviceFormProps {
  targets: { id: string; name: string }[];
  onDone: () => void;
}

function DeviceForm({ targets, onDone }: DeviceFormProps) {
  const client = useQueryClient();
  const [name, setName] = useState("");
  const [match, setMatch] = useState("");
  const [silence, setSilence] = useState(900);
  const [picked, setPicked] = useState<string[]>([]);
  const add = useMutation({
    mutationFn: api.addWatchedDevice,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["health-checks"] });
      onDone();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate({ name: name.trim(), match: match.trim(), silence_s: silence, target_ids: picked });
  };
  const input = "h-8 w-full rounded border border-border-strong bg-inset px-2 text-sm";
  return (
    <form
      onSubmit={submit}
      aria-label="Watch a device"
      className="grid gap-3 border-b border-border bg-surface-expand p-3 text-sm md:grid-cols-3"
    >
      <label className="flex flex-col gap-1">
        <span className="font-semibold">Name</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Site A network sensor"
          className={input}
        />
      </label>
      <div className="flex flex-col gap-1">
        <label className="flex flex-col gap-1">
          <span className="font-semibold">IP address or host name</span>
          <input
            value={match}
            onChange={(e) => setMatch(e.target.value)}
            placeholder="10.30.1.21 or sensor-a"
            aria-describedby="watch-match-help"
            className={`${input} font-mono`}
          />
        </label>
        <span id="watch-match-help" className="text-xs text-text-muted">
          Matched in any address or host column.
        </span>
      </div>
      <label className="flex flex-col gap-1">
        <span className="font-semibold">Unhealthy after silent for</span>
        <select
          value={silence}
          onChange={(e) => setSilence(Number(e.target.value))}
          className={input}
        >
          {SILENCE.map((o) => (
            <option key={o.s} value={o.s}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="flex flex-col gap-1 md:col-span-2">
        <legend className="mb-1 font-semibold">
          Alert when it goes silent and comes back (optional)
        </legend>
        {targets.length ? (
          <div className="flex flex-wrap gap-3">
            {targets.map((t) => (
              <label key={t.id} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={picked.includes(t.id)}
                  onChange={(e) =>
                    setPicked(
                      e.target.checked ? [...picked, t.id] : picked.filter((x) => x !== t.id),
                    )
                  }
                />
                {t.name}
              </label>
            ))}
          </div>
        ) : (
          <span className="text-text-muted">
            No alert targets yet; the page still shows its state.
          </span>
        )}
      </fieldset>
      <div className="flex items-end justify-end gap-2">
        <button
          type="submit"
          disabled={!name.trim() || !match.trim() || add.isPending}
          className="h-8 rounded bg-accent px-3 font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          Watch device
        </button>
      </div>
      <div className="md:col-span-3">
        <FormError
          message={
            add.error instanceof ApiError
              ? add.error.message
              : add.error
                ? "That did not work"
                : null
          }
        />
      </div>
    </form>
  );
}
