import { useQuery } from "@tanstack/react-query";
import { api, type Cell, type Schedule } from "@/lib/api";
import { navigate } from "@/lib/route";
import { eventsSql, seedSearch } from "@/lib/searchSeed";
import { cronLabel, counts, fillSql } from "@/features/schedules/schedule";
import { Sparkline } from "./Sparkline";

const TOP_ROWS = 5;

interface SchedulePanelProps {
  schedule: Schedule;
}

function cellText(v: Cell): string {
  if (v === null) return "·";
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}

/** One schedule on the Dashboard (SPEC 5.5): last run, count, trend, flag, top rows. */
export function SchedulePanel({ schedule: s }: SchedulePanelProps) {
  const last = s.recent[0];
  const readable = last && last.status === "ok" && !last.restricted;
  const detail = useQuery({
    queryKey: ["schedule-run", s.schedule_id, last?.run_id],
    queryFn: () => api.scheduleRun(s.schedule_id, last?.run_id ?? ""),
    enabled: Boolean(readable),
  });
  const searches = useQuery({
    queryKey: ["searches"],
    queryFn: api.searches,
    enabled: s.kind === "search",
  });
  const run = detail.data;
  const rows = (run?.sample ?? []).slice(0, TOP_ROWS);

  let openSql: string | null = null;
  if (run && readable) {
    if (s.kind === "rule") {
      openSql = eventsSql(run.sample.map((r) => String(r[0])));
    } else {
      const search = (searches.data ?? []).find((x) => x.id === s.target_id);
      if (search && run.range_start && run.range_end) {
        const values: Record<string, Cell> = {};
        for (const p of search.params) if (p.default != null) values[p.name] = p.default;
        Object.assign(values, s.params);
        openSql = fillSql(search.sql, values, run.range_start, run.range_end);
      }
    }
  }

  return (
    <section
      aria-label={s.name}
      className="flex min-w-0 flex-col gap-2 rounded-card border border-border bg-surface p-3 text-sm"
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold" title={s.name}>
            {s.name}
          </div>
          <div className="text-text-muted">
            {s.kind === "search" ? "Saved search" : "Rule"} · {cronLabel(s.cron)}
          </div>
        </div>
        {last?.flagged && !last.restricted ? (
          <span className="rounded-badge bg-sev-high-bg px-2 py-px text-xs text-sev-high-text">
            Flagged
          </span>
        ) : null}
      </div>
      {s.paused ? (
        <p className="text-warn">Paused: {s.paused_reason ?? "by a person"}</p>
      ) : !last ? (
        <p className="text-text-secondary">Not run yet</p>
      ) : last.restricted ? (
        <p className="text-text-secondary">
          Restricted: this run read sources you cannot read, so its results are hidden.
        </p>
      ) : last.status === "failed" ? (
        <p className="text-danger">Last run failed: {last.error}</p>
      ) : (
        <>
          <div className="flex items-end justify-between gap-3">
            <div>
              <div className="text-kpi">{last.row_count ?? 0}</div>
              <div className="text-text-muted">
                {s.kind === "rule" ? "matches" : "rows"} ·{" "}
                {last.started_at.slice(0, 16).replace("T", " ")}
              </div>
            </div>
            <Sparkline
              values={counts(s.recent)}
              label={`Counts of the last ${s.recent.length} runs`}
            />
          </div>
          {last.flagged && last.flag_reason ? (
            <p className="text-sev-high-text">{last.flag_reason}</p>
          ) : null}
          {rows.length && run ? (
            <div className="overflow-x-auto rounded border border-border">
              <table aria-label={`Top rows of ${s.name}`} className="w-full">
                <thead>
                  <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
                    {run.columns.map((c) => (
                      <th key={c} className="px-2 py-1 font-semibold">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i} className="border-b border-border last:border-0">
                      {r.map((v, j) => (
                        <td key={j} className="max-w-[14rem] truncate px-2 py-1 font-mono">
                          {cellText(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {openSql ? (
            <div>
              <button
                type="button"
                className="h-7 rounded border border-border px-2 text-accent-text hover:bg-surface-head"
                onClick={() => {
                  if (!openSql) return;
                  seedSearch({ sql: openSql });
                  navigate("search");
                }}
              >
                Open in Search
              </button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
