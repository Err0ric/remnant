import { useMutation, useQueries, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, type Dashboard, type Schedule } from "@/lib/api";
import { since, stamp } from "@/features/overview/time";
import { flagText, formatHeadline, headlineValue, panelLabel } from "./headline";

interface NeedsAttentionProps {
  dashboard: Dashboard;
  schedules: Map<string, Schedule>;
}

/** Flagged panels from their latest run, newest first, until acknowledged (ADR-0034 row
 * 3). Hidden when nothing is flagged. Restricted runs never show here. */
export function NeedsAttention({ dashboard, schedules }: NeedsAttentionProps) {
  const client = useQueryClient();
  const ack = useMutation({
    mutationFn: (v: { scheduleId: string; runId: string }) =>
      api.acknowledge(dashboard.dashboard_id, v.scheduleId, v.runId),
    onSuccess: () => client.invalidateQueries({ queryKey: ["dashboards"] }),
  });
  const items = dashboard.panels
    .map((p) => schedules.get(p.schedule_id))
    .filter((s): s is Schedule => {
      const last = s?.recent[0];
      return Boolean(
        s &&
        last &&
        last.flagged &&
        !last.restricted &&
        dashboard.acks[s.schedule_id] !== last.run_id,
      );
    })
    .sort((a, b) => (b.recent[0]?.started_at ?? "").localeCompare(a.recent[0]?.started_at ?? ""));
  // Each item's run (shared with its panel's query) says what a row is: "3 addresses".
  const runs = useQueries({
    queries: items.map((s) => ({
      queryKey: ["schedule-run", s.schedule_id, s.recent[0]?.run_id],
      queryFn: () => api.scheduleRun(s.schedule_id, s.recent[0]?.run_id ?? ""),
    })),
  });
  // Until a run's columns arrive, its words wait too: no "results" that turns into "addresses".
  const columnsOf = new Map(
    items.map((s, i) => [s.schedule_id, runs[i]?.data?.columns ?? null] as const),
  );
  if (items.length === 0) return null;
  const now = new Date().toISOString();
  return (
    <section aria-label="Needs attention" className="rounded-card border border-border bg-surface">
      <h2 className="border-b border-border px-3 py-2 text-sm font-semibold">
        Needs attention <span className="font-normal text-text-muted">{items.length}</span>
      </h2>
      <ul>
        {items.map((s) => {
          const last = s.recent[0];
          if (!last) return null;
          const value = headlineValue(s, last);
          const columns = columnsOf.get(s.schedule_id) ?? null;
          return (
            <li
              key={s.schedule_id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-3 py-2 text-sm last:border-0"
            >
              <span aria-hidden="true" className="h-4 w-1 rounded bg-warn" />
              <span className="min-w-0 font-semibold">{s.name}</span>
              {columns ? (
                <span className="min-w-0 text-warn">{flagText(s, last, columns)}</span>
              ) : null}
              {value !== null && columns ? (
                <span className="tabular-nums text-text-secondary">
                  {formatHeadline(value)} {panelLabel(s, columns)}
                </span>
              ) : null}
              <time
                dateTime={last.started_at}
                title={`${stamp(last.started_at)} UTC`}
                className="text-text-muted"
              >
                {since(last.started_at, now)}
              </time>
              <span className="ml-auto flex gap-2">
                <button
                  type="button"
                  onClick={() =>
                    document.getElementById(`panel-${s.schedule_id}`)?.scrollIntoView({
                      block: "center",
                    })
                  }
                  className="h-7 rounded px-2 text-accent-text hover:bg-surface-head"
                >
                  Show panel
                </button>
                <button
                  type="button"
                  aria-label={`Acknowledge ${s.name}`}
                  disabled={ack.isPending}
                  onClick={() => ack.mutate({ scheduleId: s.schedule_id, runId: last.run_id })}
                  className="h-7 rounded border border-border px-2 hover:bg-surface-head"
                >
                  Acknowledge
                </button>
              </span>
            </li>
          );
        })}
      </ul>
      {ack.isError ? (
        <p role="alert" className="px-3 pb-2 text-sm text-danger">
          {ack.error instanceof ApiError ? ack.error.message : "That did not work"}
        </p>
      ) : null}
    </section>
  );
}
