import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type AlertItem, type AlertList, type Overview, type Source } from "@/lib/api";
import { navigate, pathFor } from "@/lib/route";
import { When } from "@/components/When";
import { CloseForm } from "@/features/alerts/CloseForm";
import { KIND_LABEL } from "@/features/alerts/kinds";
import { lag } from "@/features/health/flow";

interface MorningAnswerProps {
  canClose: boolean;
  isAdmin: boolean;
}

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

/** "2 things need you: Failed SSH by address and a gap on paloalto_fw. Everything else is
 * flowing." (ADR-0037 row 5). Alerts first, then sources with a problem no alert covers. */
export function sentence(alerts: AlertList | undefined, states: SourceState[]): string {
  const covered = new Set(
    (alerts?.items ?? []).filter((i) => i.kind === "gap").map((i) => i.subject),
  );
  const broken = states.filter((s) => s.problem && !covered.has(s.id));
  // Runs of the same search, rule, or source are one thing: "Failed SSH (2 runs)".
  const groups = new Map<string, { text: string; runs: number }>();
  for (const i of alerts?.items ?? []) {
    const key = `${i.kind}:${i.subject}`;
    const g = groups.get(key);
    if (g) g.runs += 1;
    else groups.set(key, { text: i.kind === "gap" ? `a gap on ${i.subject}` : i.title, runs: 1 });
  }
  const parts = [
    ...[...groups.values()].map((g) => (g.runs > 1 ? `${g.text} (${g.runs} runs)` : g.text)),
    ...broken.map((s) => `${s.id} ${s.problem}`),
  ];
  const restricted = alerts?.restricted ?? 0;
  const n = parts.length + restricted;
  const flowing = states.filter((s) => !s.problem).length;
  if (n === 0)
    return states.length
      ? `Nothing needs you. ${flowing === states.length ? `All ${states.length}` : `${flowing} of ${states.length}`} ${states.length === 1 ? "source is" : "sources are"} flowing.`
      : "Nothing needs you.";
  const named = parts.slice(0, 2);
  const more = n - named.length;
  const list = more
    ? `${named.join(", ")} and ${more} more`
    : named.length === 2
      ? `${named[0]} and ${named[1]}`
      : (named[0] ?? "");
  const tail = flowing === states.length ? " Everything else is flowing." : "";
  return `${n} ${n === 1 ? "thing needs" : "things need"} you: ${list}.${tail}`;
}

/** The top of the Dashboard (ADR-0037 rows 5 to 8): one sentence, then Needs you and
 * Sources, each row one click from its explanation. Panels sit below. */
export function MorningAnswer({ canClose, isAdmin }: MorningAnswerProps) {
  const alerts = useQuery({ queryKey: ["alerts", "open"], queryFn: () => api.alerts("open") });
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 60_000,
  });
  if (alerts.isLoading || sources.isLoading)
    return <div aria-busy="true" className="h-28 animate-pulse rounded-card bg-surface" />;
  const states = sourceStates(sources.data ?? [], overview.data);
  const now = overview.data?.generated_at ?? new Date().toISOString();
  return (
    <section aria-label="This morning" className="rounded-card border border-border bg-surface">
      <p className="border-b border-border px-3 py-2.5 text-base font-semibold">
        {alerts.isError ? "Alerts did not load." : sentence(alerts.data, states)}
      </p>
      <div className="grid min-w-0 md:grid-cols-2 xl:grid-cols-[5fr_3fr_3fr]">
        <NeedsYou list={alerts.data} canClose={canClose} isAdmin={isAdmin} />
        <Sources states={states} overview={overview.data} now={now} />
        <New />
      </div>
    </section>
  );
}

function NeedsYou({
  list,
  canClose,
  isAdmin,
}: {
  list: AlertList | undefined;
  canClose: boolean;
  isAdmin: boolean;
}) {
  const [closing, setClosing] = useState<string | null>(null);
  const items = list?.items ?? [];
  const shown = items.slice(0, 5);
  return (
    <div className="min-w-0 border-border px-3 py-2 md:border-r">
      <h2 className="mb-1 text-sm font-semibold">
        Needs you{" "}
        <span className="font-mono font-normal tabular-nums text-text-muted">
          {list?.open ?? 0}
        </span>
      </h2>
      {shown.length === 0 ? (
        <p className="text-sm text-text-secondary">
          No open alerts.
          {list?.restricted ? ` ${list.restricted} restricted.` : ""}
        </p>
      ) : (
        <ul className="text-sm">
          {shown.map((i) => (
            <li key={i.item_id} className="border-b border-border py-1.5 last:border-0">
              <div className="flex items-center gap-x-2">
                <span aria-hidden="true" className="h-3.5 w-1 shrink-0 rounded bg-warn" />
                <a
                  href={`${pathFor("alerts")}#item=${i.item_id}`}
                  onClick={(e) => {
                    if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                    e.preventDefault();
                    navigate("alerts", `item=${i.item_id}`);
                  }}
                  className="min-w-0 truncate font-semibold text-text hover:underline"
                  title={`${i.title}: ${why(i)}`}
                >
                  {i.title}
                </a>
                {/* The reason gives way first when the column is narrow. */}
                <span className="hidden min-w-0 truncate text-text-secondary 2xl:inline">
                  {why(i)}
                </span>
                <When iso={i.created_at} className="ml-auto shrink-0 text-text-muted" />
                {canClose ? (
                  <button
                    type="button"
                    aria-label={`Close ${i.title}`}
                    onClick={() => setClosing(closing === i.item_id ? null : i.item_id)}
                    className="h-6 shrink-0 rounded border border-border px-2 text-xs hover:bg-surface-head"
                  >
                    Close
                  </button>
                ) : null}
              </div>
              {closing === i.item_id && list ? (
                <div className="mt-2">
                  <CloseForm
                    item={i}
                    reasons={list.reasons}
                    isAdmin={isAdmin}
                    onDone={() => setClosing(null)}
                  />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {items.length > shown.length || (list?.restricted ?? 0) > 0 ? (
        <button
          type="button"
          onClick={() => navigate("alerts")}
          className="mt-1 text-sm text-accent-text hover:underline"
        >
          Open Alerts
        </button>
      ) : null}
    </div>
  );
}

function why(i: AlertItem): string {
  if (i.kind === "gap") return i.resolved ?? i.detail;
  return i.why ?? KIND_LABEL[i.kind];
}

function Sources({
  states,
  overview,
  now,
}: {
  states: SourceState[];
  overview: Overview | undefined;
  now: string;
}) {
  const flowing = states.filter((s) => !s.problem).length;
  const gaps = states.reduce((n, s) => n + s.gaps, 0);
  const newest = new Map((overview?.sources ?? []).map((s) => [s.source_id, s.last_event_at]));
  const waits = states
    .map((s) => ({ id: s.id, last: newest.get(s.id) ?? null }))
    .filter((w): w is { id: string; last: string } => Boolean(w.last))
    .sort((a, b) => a.last.localeCompare(b.last));
  const worst = waits[0];
  const problems = states.filter((s) => s.problem);
  const open = (id: string) => navigate("health", `source=${encodeURIComponent(id)}`);
  return (
    <div className="min-w-0 border-t border-border px-3 py-2 md:border-t-0">
      <h2 className="mb-1 text-sm font-semibold">
        Sources{" "}
        <span className="font-normal text-text-muted">
          <span className="font-mono tabular-nums">{flowing}</span> of{" "}
          <span className="font-mono tabular-nums">{states.length}</span> flowing
        </span>
      </h2>
      <ul className="text-sm">
        {problems.map((s) => (
          <li key={s.id}>
            <button
              type="button"
              onClick={() => open(s.id)}
              className="text-left text-danger hover:underline"
            >
              <span className="font-mono">{s.id}</span> {s.problem}
            </button>
          </li>
        ))}
        <li className="text-text-secondary">
          {gaps ? `${gaps} ${gaps === 1 ? "gap" : "gaps"} in 24 hours. ` : "No gaps in 24 hours. "}
          {worst ? (
            <>
              Longest wait {lag(worst.last, now)} (
              <button type="button" onClick={() => open(worst.id)} className="hover:underline">
                {worst.id}
              </button>
              ).
            </>
          ) : null}
        </li>
      </ul>
      <button
        type="button"
        onClick={() => navigate("health", "sources")}
        className="mt-1 text-sm text-accent-text hover:underline"
      >
        Open Health
      </button>
    </div>
  );
}

/** First seen in 24 hours (ADR-0037 row 6): AI services, MCP servers, and agents whose
 * use first appears in the data in the last day (not seen in the 30 days before). A
 * review decision never makes something new. Each links to its alert when it has one. */
function New() {
  const q = useQuery({ queryKey: ["ai-watch", 7], queryFn: () => api.aiWatchSummary(7) });
  const fresh = q.data?.new ?? [];
  const KIND = { service: "AI service", mcp: "MCP server", agent: "Agent" } as const;
  return (
    <div className="min-w-0 border-t border-border px-3 py-2 md:col-span-2 xl:col-span-1 xl:border-l xl:border-t-0">
      <h2 className="mb-1 text-sm font-semibold">
        New in 24 hours{" "}
        <span className="font-mono font-normal tabular-nums text-text-muted">{fresh.length}</span>
      </h2>
      {fresh.length === 0 ? (
        <p className="text-sm text-text-secondary">No new AI services, MCP servers, or agents.</p>
      ) : (
        <ul className="text-sm">
          {fresh.slice(0, 5).map((n) => (
            <li key={`${n.kind}:${n.id}`} className="flex min-w-0 items-baseline gap-2">
              {n.item_id ? (
                <a
                  href={`${pathFor("alerts")}#item=${n.item_id}`}
                  onClick={(e) => {
                    if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                    e.preventDefault();
                    navigate("alerts", `item=${n.item_id}`);
                  }}
                  className="min-w-0 truncate text-accent-text hover:underline"
                >
                  {n.name}
                </a>
              ) : (
                <span className="min-w-0 truncate">{n.name}</span>
              )}
              <span className="shrink-0 text-text-muted">{KIND[n.kind]}</span>
              <When iso={n.first_seen} className="ml-auto shrink-0 text-text-muted" />
            </li>
          ))}
        </ul>
      )}
      {fresh.length > 5 ? (
        <button
          type="button"
          onClick={() => navigate("ai", "services")}
          className="mt-1 text-sm text-accent-text hover:underline"
        >
          {fresh.length - 5} more on AI usage
        </button>
      ) : null}
    </div>
  );
}
