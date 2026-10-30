import { useQuery } from "@tanstack/react-query";
import { LoadFailed } from "@/components/LoadFailed";
import { api, type AlertItem, type AlertList, type Overview, type Source } from "@/lib/api";
import { navigate, pathFor } from "@/lib/route";
import { When } from "@/components/When";
import { lag } from "@/features/health/flow";

interface SourceState {
  id: string;
  problem: string | null; // why it needs someone, or null when flowing
  gaps: number; // gaps in 24 hours, for the note
}

/** Each enabled source: flowing, or why not. Errors and a quiet watch need someone; a gap
 * that ended is noted but the source is flowing (Health has the detail). */
export function sourceStates(sources: Source[], o: Overview | undefined): SourceState[] {
  const volume = new Map((o?.volume ?? []).map((v) => [v.source_id, v.gaps]));
  const health = new Map((o?.sources ?? []).map((h) => [h.source_id, h]));
  const byId = new Map(sources.map((s) => [s.source_id, s]));
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
          : s?.quiet?.state === "quiet" || h?.quiet_since
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
  tone: "high" | "medium" | "low";
  text: string;
  at: string | null;
  open: () => void;
  href: string;
}

const RANK = { high: 0, medium: 1, low: 2 } as const;

/** What needs me, one line each, severity first (F62). Open alerts (runs of one search,
 * rule, or source as one line) and sources with errors or that stopped and no alert says
 * so. Hidden entirely when nothing needs me. */
export function AttentionBanner() {
  const alerts = useQuery({ queryKey: ["alerts", "open"], queryFn: () => api.alerts("open") });
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
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
  const restricted = alerts.data?.restricted ?? 0;
  if (!lines.length && !restricted) return null;
  const shown = lines.slice(0, 5);
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
                        : "bg-sev-low-bg text-sev-low-text"
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
      {lines.length > shown.length || restricted ? (
        <p className="mt-1 text-sm text-text-secondary">
          {lines.length > shown.length ? (
            <button
              type="button"
              onClick={() => navigate("alerts")}
              className="text-accent-text hover:underline"
            >
              {lines.length - shown.length} more on Alerts
            </button>
          ) : null}
          {lines.length > shown.length && restricted ? ". " : ""}
          {restricted ? `${restricted} restricted: read a source you cannot see.` : ""}
        </p>
      ) : null}
    </section>
  );
}

/** The banner's lines, most severe first, newest first within a severity. */
export function attentionLines(list: AlertList | undefined, states: SourceState[]): Line[] {
  const groups = new Map<string, { item: AlertItem; runs: number }>();
  for (const i of list?.items ?? []) {
    const key = `${i.kind}:${i.subject}`;
    const g = groups.get(key);
    if (g) g.runs += 1;
    else groups.set(key, { item: i, runs: 1 });
  }
  const covered = new Set(
    (list?.items ?? []).filter((i) => i.kind === "gap").map((i) => i.subject),
  );
  const lines: Line[] = [...groups.values()].map(({ item: i, runs }) => {
    // High first: High AI Watch items and gaps on watched sources; then the rest.
    const tone: Line["tone"] = i.severity === "high" || i.kind === "gap" ? "high" : "medium";
    // The badge column is severity only; what kind of alert it is goes in the text
    // (ADR-0038, owner 16:21).
    const badge = tone === "high" ? "High" : "Medium";
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
        badge: "High",
        tone: "high",
        text: `Source: ${s.id} ${s.problem}`,
        at: null,
        open: () => navigate("health", `source=${encodeURIComponent(s.id)}`),
        href: `${pathFor("health")}#source=${encodeURIComponent(s.id)}`,
      });
  return lines.sort(
    (a, b) => RANK[a.tone] - RANK[b.tone] || (b.at ?? "").localeCompare(a.at ?? ""),
  );
}

/** Sources at the bottom (F62): one line linking to Health. Problems also show in the
 * attention banner at the top. */
export function SourcesLine() {
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 60_000,
  });
  const failed = [sources, overview].filter((q) => q.isError && !q.data);
  if (failed.length)
    return (
      <section aria-label="Sources" className="rounded-card border border-border bg-surface">
        <LoadFailed
          what="Sources"
          error={failed[0]?.error}
          onRetry={() => failed.forEach((q) => void q.refetch())}
          retrying={failed.some((q) => q.isFetching)}
        />
      </section>
    );
  if (!sources.data || !overview.data) return null;
  const states = sourceStates(sources.data, overview.data);
  if (!states.length) return null;
  const now = overview.data.generated_at;
  const flowing = states.filter((s) => !s.problem).length;
  const gaps = states.reduce((n, s) => n + s.gaps, 0);
  const newest = new Map(overview.data.sources.map((s) => [s.source_id, s.last_event_at]));
  const worst = states
    .map((s) => ({ id: s.id, last: newest.get(s.id) ?? null }))
    .filter((w): w is { id: string; last: string } => Boolean(w.last))
    .sort((a, b) => a.last.localeCompare(b.last))[0];
  const parts = [
    `${flowing} of ${states.length} flowing`,
    worst ? `longest wait ${lag(worst.last, now)} (${worst.id})` : null,
    gaps ? `${gaps} ${gaps === 1 ? "gap" : "gaps"} in 24 hours` : "no gaps",
  ].filter(Boolean);
  return (
    <a
      href={`${pathFor("health")}#sources`}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        navigate("health", "sources");
      }}
      aria-label={`Sources: ${parts.join(", ")}. Open Health`}
      className={`block rounded-card border border-border bg-surface px-3 py-2 text-sm hover:bg-surface-head ${
        flowing < states.length ? "text-warn" : "text-text-secondary"
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
