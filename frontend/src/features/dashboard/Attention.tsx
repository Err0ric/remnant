import { useQuery } from "@tanstack/react-query";
import { LoadFailed } from "@/components/LoadFailed";
import { api, type AlertItem, type AlertLines, type Overview, type Source } from "@/lib/api";
import { navigate, pathFor } from "@/lib/route";
import { When } from "@/components/When";
import { openGaps, sourcesSummaryText } from "@/features/health/flow";
import { RESTRICTED_NOTE } from "@/features/alerts/kinds";

interface SourceState {
  id: string;
  problem: string | null; // why it needs someone, or null when flowing
  gaps: number; // gaps in 24 hours, for the note
}

/** Each enabled source: flowing, or why not. Errors and a quiet watch need someone; a gap
 * that ended is noted but the source is flowing (Health has the detail). */
/** A list from a response, or none: a body without it, or of another shape, is no list
 * (D194: a non-list here broke the whole Dashboard). */
export function listOf<T>(v: T[] | null | undefined | unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}

export function sourceStates(sources: Source[], o: Overview | undefined): SourceState[] {
  const volume = new Map(
    listOf<Overview["volume"][number]>(o?.volume).map((v) => [
      v.source_id,
      listOf<{ ongoing?: boolean; hours?: number }>(v.gaps),
    ]),
  );
  const health = new Map(
    listOf<Overview["sources"][number]>(o?.sources).map((h) => [h.source_id, h]),
  );
  const byId = new Map(listOf<Source>(sources).map((s) => [s.source_id, s]));
  const ids = [...new Set([...byId.keys(), ...health.keys()])].sort();
  return ids
    .filter((id) => byId.get(id)?.enabled ?? true)
    .map((id) => {
      const s = byId.get(id);
      const h = health.get(id);
      const gaps = volume.get(id) ?? [];
      const ongoing = gaps.find((g) => g.ongoing);
      const problem =
        s?.status.state === "error" || h?.state === "error"
          ? "has errors"
          : s?.quiet?.state === "quiet" || h?.quiet_since || h?.gap_alert
            ? "stopped sending"
            : ongoing
              ? `has sent nothing for ${ongoing.hours} h`
              : null;
      return { id, problem, gaps: gaps.length };
    });
}

interface Line {
  key: string;
  badge: string;
  tone: "high" | "medium" | "none";
  text: string;
  at: string | null;
  open: () => void;
  href: string;
}

const RANK = { high: 0, medium: 1, none: 2 } as const;
const SEV_LABEL = { high: "High", medium: "Medium", none: "" } as const;
/** Lines the banner shows. */
const SHOWN = 5;

/** What needs me, one line each, severity first (F62). Open alerts (runs of one search,
 * rule, or source as one line) and sources with errors or that stopped and no alert says
 * so. Hidden entirely when nothing needs me. */
export function AttentionBanner() {
  // Only the lines shown (owner, 2026-11-11: the audit log records access, not page loads).
  const alerts = useQuery({
    queryKey: ["alerts", "lines", SHOWN, "severity"],
    queryFn: () => api.alertLines(SHOWN),
  });
  const sources = useQuery({ queryKey: ["source-list"], queryFn: api.sources });
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 60_000,
  });
  const failed = [alerts, sources, overview].filter((q) => q.isError && !q.data);
  if (failed.length)
    return (
      <section
        aria-label="Needs you"
        className="rounded-card border border-border border-l-4 border-l-warn bg-surface"
      >
        <LoadFailed
          what="Needs you"
          error={failed[0]?.error}
          onRetry={() => failed.forEach((q) => void q.refetch())}
          retrying={failed.some((q) => q.isFetching)}
        />
      </section>
    );
  const states = sourceStates(sources.data ?? [], overview.data);
  const lines = attentionLines(alerts.data, states);
  const restricted = alerts.data?.restricted === true;
  // Alert lines the server left out are counted, not sent.
  const total =
    lines.length + Math.max(0, (alerts.data?.groups ?? 0) - (alerts.data?.items.length ?? 0));
  if (!total && !restricted) return null;
  const shown = lines.slice(0, SHOWN);
  return (
    <section
      aria-label="Needs you"
      className="rounded-card border border-border border-l-4 border-l-warn bg-surface px-3 py-2"
    >
      <table className="w-full table-fixed text-sm">
        <colgroup>
          <col className="w-[5.5rem]" />
          <col />
          <col className="w-40" />
        </colgroup>
        <thead className="sr-only">
          <tr>
            <th>Severity</th>
            <th>What fired</th>
            <th>When</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((l) => (
            <tr key={l.key}>
              <td className="py-0.5 pr-2 align-middle">
                <span
                  className={`block rounded-badge px-1.5 text-center text-xs font-semibold ${
                    l.tone === "high"
                      ? "bg-sev-high-bg text-sev-high-text"
                      : l.tone === "medium"
                        ? "bg-sev-medium-bg text-sev-medium-text"
                        : ""
                  }`}
                >
                  {l.badge}
                </span>
              </td>
              <td className="py-0.5">
                <a
                  href={l.href}
                  onClick={(e) => {
                    if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                    e.preventDefault();
                    l.open();
                  }}
                  className="block truncate text-text hover:underline"
                  title={l.text}
                >
                  {l.text}
                </a>
              </td>
              <td className="whitespace-nowrap py-0.5 pl-2 text-right align-middle">
                {l.at ? <When iso={l.at} className="text-text-muted" /> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {total > shown.length || restricted ? (
        <p className="mt-1 text-sm text-text-secondary">
          {total > shown.length ? (
            <button
              type="button"
              onClick={() => navigate("alerts")}
              className="text-accent-text hover:underline"
            >
              {total - shown.length} more on Alerts
            </button>
          ) : null}
          {total > shown.length && restricted ? ". " : ""}
          {restricted ? RESTRICTED_NOTE : ""}
        </p>
      ) : null}
    </section>
  );
}

/** The banner's lines, most severe first, newest first within a severity. `list` is the
 * server's lines (one per kind and subject, with their runs), or a plain list grouped here. */
export function attentionLines(
  list: (Pick<AlertLines, "items"> & Partial<Pick<AlertLines, "runs" | "gap_sources">>) | undefined,
  states: SourceState[],
): Line[] {
  const groups = new Map<string, { item: AlertItem; runs: number }>();
  for (const i of list?.items ?? []) {
    const key = `${i.kind}:${i.subject}`;
    const g = groups.get(key);
    if (g) g.runs += 1;
    else groups.set(key, { item: i, runs: list?.runs?.[i.item_id] ?? 1 });
  }
  const covered = new Set([
    ...(list?.gap_sources ?? []),
    ...(list?.items ?? []).filter((i) => i.kind === "gap").map((i) => i.subject),
  ]);
  const lines: Line[] = [...groups.values()].map(({ item: i, runs }) => {
    // The severity stored on the alert, as the Alerts page shows it; never re-derived
    // here from the kind (review item 2: gaps showed High here and Medium on Alerts).
    const tone: Line["tone"] = i.severity ?? "none";
    // The badge column is severity only; what kind of alert it is goes in the text
    // (ADR-0038, owner 16:21).
    const badge = SEV_LABEL[tone];
    const kind =
      i.kind === "schedule"
        ? "Schedule"
        : i.kind === "rule"
          ? "Rule"
          : i.kind === "gap"
            ? "Source gap"
            : "AI Watch";
    // The reason is left out when the title already says it ("AI service not approved").
    const reason = why(i);
    const said =
      !reason ||
      i.kind === "gap" ||
      // AI Watch titles already name the decision needed ("AI service not reviewed").
      (i.kind === "ai_watch" && /^(not reviewed yet|not approved)$/i.test(reason)) ||
      i.title.toLowerCase().includes(reason.toLowerCase());
    const what = `${kind}: ${said ? i.title : `${i.title}: ${reason}`}`;
    return {
      key: `a:${i.item_id}`,
      badge,
      tone,
      text: runs > 1 ? `${what} (${runs} runs)` : what,
      at: i.created_at,
      open: () => navigate("alerts", `item=${i.item_id}`),
      href: `${pathFor("alerts")}#item=${i.item_id}`,
    };
  });
  for (const s of states)
    if (s.problem && !covered.has(s.id))
      lines.push({
        key: `s:${s.id}`,
        // No alert says so (a source without Alert if quiet, or one the viewer cannot
        // see the alert for): shown as a source gap would be (ADR-0043 row 15).
        badge: SEV_LABEL.medium,
        tone: "medium",
        text: `Source: ${s.id} ${s.problem}`,
        at: null,
        open: () => navigate("health", `source=${encodeURIComponent(s.id)}`),
        href: `${pathFor("health")}#source=${encodeURIComponent(s.id)}`,
      });
  return lines.sort(
    (a, b) => RANK[a.tone] - RANK[b.tone] || (b.at ?? "").localeCompare(a.at ?? ""),
  );
}

/** Whether Health needs attention: a source not healthy or an open gap. The top banner
 * shows then and the bottom Sources line steps aside (owner, 2026-11-12: no duplicate). */
function needsHealth(o: Overview): boolean {
  const summary = o.source_summary;
  if (!summary?.total) return false;
  return summary.healthy < summary.total || openGaps(o).length > 0;
}

/** Where the bottom Sources line links: the gap alerts when there are any (the one alert
 * when there is one); otherwise Health. The Health banner always opens Health (D243). */
function sourcesTarget(o: Overview): readonly ["alerts" | "health", string] {
  const alerted = openGaps(o).filter((g) => g.item_id);
  const one = alerted.length === 1 ? alerted[0]?.item_id : null;
  return alerted.length
    ? (["alerts", one ? `item=${one}` : ""] as const)
    : (["health", "sources"] as const);
}

/** Health problems at the top of the Dashboard, one line linking to Health (owner,
 * 2026-11-12: "/" always opens the Dashboard). The Sources line's own data and words, so it
 * adds no query; hidden when every source is healthy and no gap is open. */
export function HealthBanner() {
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 60_000,
  });
  const summary = overview.data?.source_summary;
  if (!overview.data || !summary?.total || !needsHealth(overview.data)) return null;
  const text = sourcesSummaryText(summary, overview.data.generated_at);
  const said = [text.headline, ...text.details].join(", ");
  return (
    <section
      aria-label="Health needs attention"
      className="flex min-w-0 items-center gap-2 rounded-card border border-border border-l-4 border-l-warn bg-surface px-3 py-2 text-sm"
    >
      <span className="font-semibold">Health</span>
      <span className="min-w-0 flex-1 truncate text-text-secondary" title={`Sources ${said}`}>
        Sources {said}
      </span>
      <a
        href={`${pathFor("health")}#sources`}
        onClick={(e) => {
          if (e.metaKey || e.ctrlKey || e.shiftKey) return;
          e.preventDefault();
          navigate("health", "sources");
        }}
        className="shrink-0 text-accent-text hover:underline"
      >
        Open Health
      </a>
    </section>
  );
}

/** Sources at the bottom (F62): one line linking to Health, shown when every source is
 * healthy. When Health needs attention the banner at the top says it instead, so this line
 * is not shown twice (owner, 2026-11-12). */
export function SourcesLine() {
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 60_000,
  });
  if (overview.isError && !overview.data)
    return (
      <section aria-label="Sources" className="rounded-card border border-border bg-surface">
        <LoadFailed
          what="Sources"
          error={overview.error}
          onRetry={() => void overview.refetch()}
          retrying={overview.isFetching}
        />
      </section>
    );
  const summary = overview.data?.source_summary;
  if (!overview.data || !summary?.total || needsHealth(overview.data)) return null;
  // The same words as Health's Sources tile, from the same server summary (handoff item 4).
  const text = sourcesSummaryText(summary, overview.data.generated_at);
  const parts = [text.headline, ...text.details];
  const open = openGaps(overview.data);
  const [area, section] = sourcesTarget(overview.data);
  return (
    <a
      href={`${pathFor(area)}${section ? `#${section}` : ""}`}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        navigate(area, section || undefined);
      }}
      aria-label={`Sources: ${parts.join(", ")}. Open ${area === "alerts" ? "Alerts" : "Health"}`}
      className={`block rounded-card border border-border bg-surface px-3 py-2 text-sm hover:bg-surface-head ${
        summary.healthy < summary.total || open.length ? "text-warn" : "text-text-secondary"
      }`}
    >
      <span className="font-semibold text-text">Sources</span> {parts.join(", ")}
    </a>
  );
}

function why(i: AlertItem): string {
  if (i.kind === "gap") return i.resolved ?? i.detail;
  return i.why ?? "";
}
