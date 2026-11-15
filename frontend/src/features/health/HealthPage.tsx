import { Card } from "@/components/Card";
import { FilterBar } from "@/components/FilterBar";
import { Skeleton } from "@/components/Skeleton";
import { localStamp } from "@/lib/localTime";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { FormError } from "@/features/auth/FormError";
import { since, stamp } from "@/features/overview/time";
import {
  ApiError,
  api,
  type BackupHealth,
  type ClientErrorRow,
  type Source,
  type WatchedDevice,
} from "@/lib/api";
import {
  fragmentValues,
  healthStatus,
  navigate,
  setFragment,
  useSection,
  useSectionTab,
  type HealthStatus,
  type PageId,
} from "@/lib/route";
import { SpeedTable } from "./SpeedTable";
import { BackgroundFailures } from "./BackgroundFailures";
import { EntityLink } from "@/components/EntityLink";
import { idleText, openGaps, quietWord } from "./flow";
import { heldText } from "@/features/sources/VendorAlertNotify";
import { SourceFlow } from "./SourceFlow";
import { StatusLine } from "./StatusLine";
import { SystemStrip, type SourceTally } from "./SystemStrip";

type Level = "unhealthy" | "attention" | "paused" | "healthy";
type TabId =
  "sources" | "enrichment" | "agents" | "devices" | "alerts" | "backups" | "rollups" | "speed";

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
  /** Hover text for the detail line (a UTC time). */
  detailTitle?: string;
  /** The reason is only the quiet sentence, left out under a gap's own sentence (D255). */
  quietNote?: boolean;
}

const LEVELS: { id: Level; label: string; color: string }[] = [
  { id: "unhealthy", label: "Unhealthy", color: "border-t-danger text-danger" },
  { id: "attention", label: "Needs attention", color: "border-t-warn text-warn" },
  { id: "paused", label: "Paused", color: "border-t-border-strong text-text-secondary" },
  { id: "healthy", label: "Healthy", color: "border-t-ok text-ok" },
];
const BADGE: Record<Level, string> = {
  unhealthy: "border border-danger text-danger",
  attention: "border border-warn text-warn",
  paused: "bg-info-bg text-info-tx",
  healthy: "bg-local-bg text-local-tx",
};
/** The Status filter (D255): Problems is Unhealthy and Needs attention together. */
const STATUSES: { id: HealthStatus; label: string; levels: Level[] }[] = [
  { id: "all", label: "All", levels: ["unhealthy", "attention", "paused", "healthy"] },
  { id: "problems", label: "Problems", levels: ["unhealthy", "attention"] },
  { id: "paused", label: "Paused", levels: ["paused"] },
  { id: "healthy", label: "Healthy", levels: ["healthy"] },
];
/** What the bar's count counts, one and many. */
const NOUN: Record<TabId, [string, string]> = {
  sources: ["source", "sources"],
  enrichment: ["feed", "feeds"],
  agents: ["agent", "agents"],
  devices: ["device", "devices"],
  alerts: ["target or schedule", "targets and schedules"],
  backups: ["backup", "backups"],
  rollups: ["rollup", "rollups"],
  speed: ["route", "routes"],
};
const TABS: { id: TabId; label: string }[] = [
  { id: "sources", label: "Sources" },
  { id: "enrichment", label: "Enrichment feeds" },
  { id: "agents", label: "Endpoint agents" },
  { id: "devices", label: "Watched devices" },
  { id: "alerts", label: "Delivery" },
  { id: "backups", label: "Backups" },
  { id: "rollups", label: "Page rollups" },
  { id: "speed", label: "Speed" },
];
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
      quietNote: true,
    };
  if (s.alert_pause)
    return {
      ...base,
      level: "attention",
      reason: `Over 100 new alerts an hour: below High stored, not raised (${heldText(s.alert_pause)})`,
    };
  if (st.warnings?.length) return { ...base, level: "attention", reason: st.warnings.join("; ") };
  if (st.retry_at)
    return { ...base, level: "attention", reason: `Retrying at ${localStamp(st.retry_at)}` };
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
  /** "system": Settings > System, with Backups, Page rollups, and Speed (they were Health
   * tabs; ADR-0052 section 3.3), and none of Health's own strip. */
  scope?: "health" | "system";
}

// The pages' tabs, and the Type each merged tab filters by (the old tabs it holds).
const HEALTH_VIEWS = ["sources", "collectors", "delivery"] as const;
type View = (typeof HEALTH_VIEWS)[number] | "system";
const TYPES: Partial<Record<View, { id: TabId; label: string }[]>> = {
  sources: [
    { id: "sources", label: "Events" },
    { id: "enrichment", label: "Enrichment feeds" },
  ],
  collectors: [
    { id: "agents", label: "Endpoint agents" },
    { id: "devices", label: "Watched devices" },
  ],
  system: [
    { id: "backups", label: "Backups" },
    { id: "rollups", label: "Page rollups" },
    { id: "speed", label: "Speed" },
  ],
};

/** Health (ADR-0019): is every source, connector, agent, watched device, alert target,
 * and schedule working, on one page. */
export function HealthPage({ isAdmin, scope = "health" }: HealthPageProps) {
  const client = useQueryClient();
  const [healthView] = useSectionTab<View>(HEALTH_VIEWS);
  const view: View = scope === "system" ? "system" : healthView;
  // `#source=<id>` (alert messages, the Dashboard, Settings) opens Sources at that row.
  const section = useSection();
  const frag = fragmentValues(section);
  const focused = frag.get("source");
  // The Type filter of a merged tab, in the address (`#type=enrichment`); the first type
  // is the usual one and is left out. `tab` is the kind of row the table lists.
  const types = TYPES[view];
  const asked = frag.get("type");
  const tab: TabId =
    focused && view === "sources"
      ? "sources"
      : (types?.find((t) => t.id === asked)?.id ?? types?.[0]?.id ?? "alerts");
  const setType = (id: TabId) => {
    const next = fragmentValues(section);
    next.delete("source");
    if (id === types?.[0]?.id) next.delete("type");
    else next.set("type", id);
    setFragment(next.toString());
  };
  // The Status filter, in the address too (`#status=problems`); All is left out (D255).
  const status = healthStatus(frag);
  const levels = STATUSES.find((x) => x.id === status)?.levels ?? [];
  const setStatus = (id: HealthStatus) => {
    const next = fragmentValues(section);
    if (id === "all") next.delete("status");
    else next.set("status", id);
    setFragment(next.toString());
  };
  const resetFilters = () => {
    const next = fragmentValues(section);
    for (const k of ["type", "status", "source"]) next.delete(k);
    setFragment(next.toString());
  };
  const [adding, setAdding] = useState(false);
  // Settings > System shows only what the checks report: none of Health's other reads
  // (the Overview is audited when it computes).
  const onHealth = scope !== "system";
  const sources = useQuery({
    queryKey: ["source-list"],
    queryFn: api.sources,
    enabled: onHealth,
  });
  const checks = useQuery({
    queryKey: ["health-checks"],
    queryFn: api.healthChecks,
    refetchInterval: 60_000,
  });
  const schedules = useQuery({
    queryKey: ["schedules"],
    queryFn: api.schedules,
    enabled: onHealth,
  });
  // Flow, gaps, totals, detections, and delivery (F55; the former Overview's numbers).
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 60_000,
    enabled: onHealth,
  });
  // The newest open alert only (owner, 2026-11-11: the audit log records access, not loads).
  const alerts = useQuery({
    queryKey: ["alerts", "lines", 1, "newest"],
    queryFn: () => api.alertLines(1, "newest"),
    enabled: onHealth,
  });
  const enrichment = useQuery({
    queryKey: ["enrichment"],
    queryFn: api.enrichment,
    enabled: onHealth,
  });
  const targets = useQuery({
    queryKey: ["alert-targets"],
    queryFn: api.alertTargets,
    enabled: isAdmin && onHealth,
  });
  const remove = useMutation({
    mutationFn: api.removeWatchedDevice,
    onSuccess: () => client.invalidateQueries({ queryKey: ["health-checks"] }),
  });

  const now = new Date().toISOString();
  const list = sources.data ?? [];
  // Each source's level comes from the server's one condition (handoff item 4), the same
  // one the Dashboard footer counts; the reading status above only gives the words.
  const judged = new Map((overview.data?.sources ?? []).map((h) => [h.source_id, h]));
  const flowing = (r: Row): Row => {
    const h = judged.get(r.key);
    if (!h || !overview.data) return r; // the overview is still loading
    switch (h.condition) {
      case "paused":
        return { ...r, level: "paused", reason: r.reason ?? "Turned off" };
      case "error":
        return { ...r, level: "unhealthy" };
      case "quiet": {
        const word = quietWord(h.last_event_at, overview.data.generated_at);
        return {
          ...r,
          level: h.quiet_since ? "unhealthy" : "attention",
          word: word.charAt(0).toUpperCase() + word.slice(1),
        };
      }
      case "gap":
        return { ...r, level: "attention", word: "Gap" };
      case "attention":
        return { ...r, level: "attention", reason: r.reason ?? "Needs a look" };
      default:
        // Marked "Quiet is normal" and silent inside its days (D260): healthy, said in a word.
        return h.idle
          ? {
              ...r,
              level: "healthy",
              word: "Idle",
              reason: idleText(h.last_event_at, overview.data.generated_at),
            }
          : { ...r, level: "healthy", reason: null };
    }
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
          // F67: an unchanged list confirmed by a check is current as of that check.
          last:
            f.confirmed_at && f.installed_at && f.confirmed_at > f.installed_at
              ? f.confirmed_at
              : f.installed_at,
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
      detail: [
        a.kind,
        `${a.events_24h.toLocaleString()} events in 24 h`,
        // The hooks plugin's offline queue (ADR-0026): waiting, late, lost, never arrived.
        a.queued ? `${a.queued.toLocaleString()} queued at last check-in` : "",
        a.late_24h ? `${a.late_24h.toLocaleString()} delivered late` : "",
        a.dropped_24h ? `${a.dropped_24h.toLocaleString()} lost` : "",
        a.missing ? `${a.missing.toLocaleString()} missing` : "",
      ]
        .filter(Boolean)
        .join(" · "),
      last: a.last_seen,
      level: a.state === "unknown" ? "attention" : a.state,
      reason: [a.reason, ...(a.gaps ?? [])].filter(Boolean).join("; "),
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
        page: "targets",
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
    // Scheduled backups (handoff item 8): last run, its age, size, and result.
    backups: backupRows(checks.data?.backup),
    // The daily and today-so-far page rollups: whether they are keeping up (owner,
    // 2026-11-01). The time shown is the last today-so-far build, every 5 minutes.
    rollups: (checks.data?.rollups ?? []).map((ru): Row => ({
      key: `rollup:${ru.name}`,
      name: ru.label,
      sub: ru.name,
      detail: [
        `${ru.days_built.toLocaleString()} days built`,
        ru.pending === null ? "still to build: not checked yet" : `${ru.pending} still to build`,
        ru.last_built ? `last day built ${since(ru.last_built, now)}` : "no day built yet",
        ru.today_cutoff ? `today up to ${localStamp(ru.today_cutoff)}` : "",
      ]
        .filter(Boolean)
        .join(" · "),
      last: ru.today_built,
      level: ru.state === "unknown" ? "attention" : (ru.state as Level),
      reason: ru.reason,
    })),
    speed: [], // its own table (SpeedTable), not status rows
  };
  const o = overview.data;
  const tally: SourceTally | undefined = o?.source_summary
    ? { summary: o.source_summary, openGaps: openGaps(o) }
    : undefined;
  // A part shows its number once its own data is there (D255): a query that has answered,
  // or is not asked for on this page. A failed read is not data: its counts stay absent, as
  // while loading, and the error is said instead.
  const settled = (q: {
    isPending: boolean;
    fetchStatus: string;
    isError: boolean;
    data?: unknown;
  }) => (!q.isPending || q.fetchStatus === "idle") && (q.data !== undefined || !q.isError);
  // Listed: the rows are there. Levelled: their levels are too (a source's level is the
  // overview's condition).
  const listed: Record<TabId, boolean> = {
    sources: settled(sources) && settled(checks),
    enrichment: settled(enrichment),
    agents: settled(checks),
    devices: settled(checks),
    alerts: settled(schedules) && settled(targets),
    backups: settled(checks),
    rollups: settled(checks),
    speed: true,
  };
  const levelled: Record<TabId, boolean> = {
    ...listed,
    sources: listed.sources && settled(overview),
  };
  const real = (k: TabId) => rows[k].filter((r) => r.key !== "lake-quarantine");
  const bad = (rs: Row[]) =>
    rs.filter((r) => r.level === "unhealthy" || r.level === "attention").length;
  // The damaged-files notice is a state notice: counted under Problems, never filtered away.
  const shown = rows[tab].filter((r) => r.key === "lake-quarantine" || levels.includes(r.level));
  const error =
    sources.error ??
    checks.error ??
    (onHealth ? (overview.error ?? alerts.error ?? enrichment.error ?? schedules.error) : null);
  const loading = !listed[tab] && !error;
  // Problems per tab, only once every type on it is judged; a problem on any type of a tab
  // shows on the tab. No totals (DESIGN.md 6.0: a count only where something needs action).
  const tabProblems: Record<string, number> = {};
  for (const [label, kinds] of [
    ["Sources", ["sources", "enrichment"]],
    ["Collectors", ["agents", "devices"]],
    ["Delivery", ["alerts"]],
  ] as [string, TabId[]][])
    if (kinds.every((k) => levelled[k])) tabProblems[label] = bad(kinds.flatMap((k) => rows[k]));
  const total = real(tab).length;
  // A tab with nothing listed has nothing to filter: no Status row of zeros (D255).
  const hasStatus = tab !== "speed" && (!levelled[tab] || total > 0);
  const showing = shown.filter((r) => r.key !== "lake-quarantine").length;

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        title={scope === "system" ? "System" : "Health"}
        tabProblems={scope === "system" ? undefined : tabProblems}
        count={
          scope === "system"
            ? null
            : o
              ? `Updated ${since(o.generated_at, now)}`
              : "Checked every minute"
        }
      />
      <div className="flex flex-col gap-3 px-5 py-3">
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error instanceof ApiError ? error.message : "Could not load health"}
          </p>
        ) : null}
        {types || hasStatus ? (
          <FilterBar
            label={scope === "system" ? "Choose what to show" : "Filter health"}
            facets={
              types
                ? [
                    {
                      name: "Type",
                      value: tab,
                      options: types,
                      onChange: (id) => setType(id as TabId),
                    },
                  ]
                : []
            }
            state={
              !hasStatus
                ? undefined
                : {
                    label: "Status",
                    value: status,
                    onChange: setStatus,
                    options: STATUSES.map((x) => ({
                      id: x.id,
                      label: x.label,
                      count: levelled[tab]
                        ? rows[tab].filter((r) => x.levels.includes(r.level)).length
                        : undefined,
                    })),
                  }
            }
            count={
              !hasStatus || !levelled[tab]
                ? null
                : `${showing === total ? "" : `${showing.toLocaleString()} of `}${total.toLocaleString()} ${NOUN[tab][total === 1 ? 0 : 1]}`
            }
            onReset={resetFilters}
            isDefault={status === "all" && (!types || tab === types[0]?.id)}
          />
        ) : null}
        {scope === "system" ? null : (
          <SystemStrip
            overview={o}
            tally={tally}
            alerts={alerts.data}
            overviewFailed={overview.isError && !o ? () => void overview.refetch() : undefined}
            alertsFailed={alerts.isError && !alerts.data ? () => void alerts.refetch() : undefined}
            isAdmin={isAdmin}
            now={now}
          />
        )}
        {o && scope !== "system" ? <StatusLine overview={o} now={now} /> : null}
        {isAdmin && checks.data?.background_failures?.length ? (
          <BackgroundFailures rows={checks.data.background_failures} now={now} />
        ) : null}
        {isAdmin && checks.data?.client_errors?.length ? (
          <BrowserErrors rows={checks.data.client_errors} now={now} />
        ) : null}

        {tab === "speed" ? (
          isAdmin ? (
            <SpeedTable />
          ) : (
            <p className="text-sm text-text-secondary">Page speed is for administrators.</p>
          )
        ) : (
          <>
            <Card title={TABS.find((t) => t.id === tab)?.label ?? ""}>
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
                  focused={focused}
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
                      quietNote: r.quietNote,
                      last: r.last,
                      // Its settings, at the same row (F61): one more click from Health.
                      onOpen: r.page
                        ? () =>
                            r.page === "sources"
                              ? navigate("sources", `source=${encodeURIComponent(r.name)}`)
                              : navigate(r.page as PageId)
                        : undefined,
                    }))}
                />
              ) : shown.length === 0 && loading ? (
                <Skeleton label="health" rows={5} className="rounded-none border-0" />
              ) : shown.length === 0 ? (
                <p className="p-4 text-sm text-text-muted">
                  {!listed[tab]
                    ? "This list did not load."
                    : status !== "all" && rows[tab].length
                      ? "Nothing in this state here."
                      : EMPTY[tab]}
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table
                    className="w-full text-sm"
                    aria-label={TABS.find((t) => t.id === tab)?.label}
                  >
                    <thead>
                      <tr className="border-b border-border text-left text-text-secondary">
                        <th className="px-3 py-2">Name</th>
                        <th className="hidden px-3 py-2 md:table-cell">
                          {tab === "enrichment"
                            ? "Last updated"
                            : tab === "backups"
                              ? "Last backup"
                              : tab === "rollups"
                                ? "Today built"
                                : "Last seen"}
                        </th>
                        {tab === "devices" ? (
                          <th className="hidden px-3 py-2 md:table-cell">Last 24 hours</th>
                        ) : null}
                        <th className="hidden px-3 py-2 text-right md:table-cell">State</th>
                      </tr>
                    </thead>
                    <tbody>
                      {shown.map((r) => (
                        <tr
                          key={r.key}
                          className="border-b border-border align-top last:border-b-0"
                        >
                          <td className="min-w-0 px-3 py-2">
                            {r.page ? (
                              <button
                                type="button"
                                onClick={() => navigate(r.page as PageId)}
                                className="break-all text-left font-mono text-accent-text hover:underline"
                              >
                                {r.name}
                              </button>
                            ) : tab === "agents" ? (
                              <EntityLink kind="host" value={r.name} className="font-mono" />
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
                              <div className="break-all font-mono text-xs text-text-muted">
                                {r.sub}
                              </div>
                            ) : null}
                            {r.detail ? (
                              <div className="text-xs text-text-muted" title={r.detailTitle}>
                                {r.detail}
                              </div>
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
            </Card>
          </>
        )}
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

const RESULT: Record<string, string> = {
  success: "Succeeded",
  failed: "Failed",
  skipped: "Skipped",
  running: "Running now",
};

function size(bytes: number): string {
  return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${(bytes / 1e6).toFixed(1)} MB`;
}

/** One row for scheduled backups: the last run in local time (UTC on hover), its size and
 * result, and the schedule. */
function backupRows(b: BackupHealth | null | undefined): Row[] {
  if (!b) return [];
  const last = b.last;
  return [
    {
      key: "backup",
      name: "Scheduled backup",
      sub: b.enabled ? `Daily at ${b.at_time} ${b.timezone}, ${b.keep} kept` : "Turned off",
      detail: [
        last ? `Last run ${localStamp(last.started_at)}` : "No run yet",
        last ? (RESULT[last.result] ?? last.result) : "",
        last?.bytes ? size(last.bytes) : "",
        `${b.kept} on disk`,
        b.next_at ? `next ${localStamp(b.next_at)}` : "",
      ]
        .filter(Boolean)
        .join(" · "),
      detailTitle: last ? `${stamp(last.started_at)} UTC` : undefined,
      last: b.last_success_at,
      level: b.state,
      reason: b.reason,
      page: "about",
    },
  ];
}

const EMPTY: Record<TabId, ReactNode> = {
  backups: "Backups are not reported yet.",
  rollups: "No rollups reported yet.",
  sources:
    "No sources yet. Add files, a syslog listener, Loki, or Microsoft 365 under Settings, Sources and connectors.",
  enrichment:
    "No enrichment feeds yet: GeoIP and threat intel feeds show here once set up under Settings, Enrichment.",
  agents:
    "No agents reporting. Claude Code telemetry, endpoint agents, and the MCP inventory show one row per machine.",
  devices:
    "No watched devices. Add a network sensor, collector, or firewall by address or host name to know when it goes silent.",
  alerts: "No alert targets or schedules you can see.",
  speed: "No page loads recorded yet.",
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
  const input = "h-8 w-full rounded border border-border-control bg-inset px-2 text-sm";
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

const KIND_TEXT: Record<ClientErrorRow["kind"], string> = {
  render: "Page failed",
  panel: "Panel failed",
  chunk: "Page file missing",
  unhandled: "Script error",
};

/** Pages and panels that failed in people's browsers (owner 2026-11-02): when, where, the
 * error id the person sees, and whether the tab ran an older build than the server. */
function BrowserErrors({ rows, now }: { rows: ClientErrorRow[]; now: string }) {
  return (
    <section
      aria-label="Browser errors"
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <h2 className="border-b border-border bg-surface-head px-3 py-2 text-base font-semibold">
        Browser errors, last 24 hours
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-text-secondary">
              <th className="px-3 py-2">When</th>
              <th className="px-3 py-2">What</th>
              <th className="px-3 py-2">Page</th>
              <th className="px-3 py-2">Error</th>
              <th className="px-3 py-2">Error id</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.error_id + e.at} className="border-b border-border last:border-0">
                <td className="px-3 py-2" title={`${stamp(e.at)} UTC`}>
                  {since(e.at, now)}
                </td>
                <td className="px-3 py-2">
                  {KIND_TEXT[e.kind]}
                  {e.stale ? (
                    <span className="text-text-muted"> (older build in an open tab)</span>
                  ) : null}
                </td>
                <td className="px-3 py-2 font-mono">{e.route}</td>
                <td className="px-3 py-2 font-mono text-text-secondary">
                  {e.name}: {e.message}
                </td>
                <td className="px-3 py-2 font-mono">{e.error_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
