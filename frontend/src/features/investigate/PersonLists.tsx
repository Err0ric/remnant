import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { EntityLink } from "@/components/EntityLink";
import { LoadFailed } from "@/components/LoadFailed";
import { When } from "@/components/When";
import { api, type QueryResult } from "@/lib/api";
import { cn } from "@/lib/cn";
import { drillSql, openDrill } from "@/lib/drill";
import { navigate, navigateTab } from "@/lib/route";
import { ResultsTable } from "@/features/search/ResultsTable";

const TH = "px-3 py-2 font-semibold";
const TD = "px-3 py-1.5";

function Box({
  label,
  note,
  action,
  children,
}: {
  label: string;
  note?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      aria-label={label}
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border bg-surface-head px-3 py-2">
        <h2 className="text-base font-semibold">{label}</h2>
        {note ? <span className="text-sm text-text-muted">{note}</span> : null}
        {action ? <span className="ml-auto">{action}</span> : null}
      </div>
      {children}
    </section>
  );
}

/** The person's Claude sessions, last 30 days (ADR-0038 row 27); each opens in Agents. */
export function PersonSessions({ person }: { person: string }) {
  const q = useQuery({
    queryKey: ["person-sessions", person],
    queryFn: () => api.aiSessions(30, person),
  });
  return (
    <Box label="Sessions" note="Claude Code and Cowork sessions, last 30 days">
      {q.isLoading ? (
        <div aria-busy="true" className="h-24 animate-pulse" />
      ) : q.isError ? (
        <LoadFailed
          what="sessions"
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
        />
      ) : !q.data?.length ? (
        <p className="px-3 py-4 text-sm text-text-secondary">
          No sessions by this person in the last 30 days, in the sources you can read.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-secondary">
                <th className={TH}>Started</th>
                <th className={TH}>Device</th>
                <th className={`${TH} text-right`}>Prompts</th>
                <th className={`${TH} text-right`}>Tool calls</th>
                <th className={`${TH} text-right`}>Failed</th>
                <th className={TH}>State</th>
              </tr>
            </thead>
            <tbody>
              {q.data.map((s) => (
                <tr key={s.session_id} className="border-b border-border last:border-0">
                  <td className={`${TD} whitespace-nowrap`}>
                    <button
                      type="button"
                      onClick={() =>
                        navigateTab(
                          "agents",
                          "sessions",
                          `session=${encodeURIComponent(s.session_id)}`,
                        )
                      }
                      className="text-accent-text hover:underline"
                    >
                      <When iso={s.started} />
                    </button>
                  </td>
                  <td className={`${TD} font-mono`}>
                    {s.machine ? <EntityLink kind="host" value={s.machine} /> : "·"}
                  </td>
                  <td className={`${TD} text-right font-mono tabular-nums`}>{s.prompts}</td>
                  <td className={`${TD} text-right font-mono tabular-nums`}>{s.tool_calls}</td>
                  <td
                    className={cn(
                      `${TD} text-right font-mono tabular-nums`,
                      s.failed ? "text-warn" : "text-text-muted",
                    )}
                  >
                    {s.failed ?? 0}
                  </td>
                  <td className={`${TD} text-text-secondary`}>{s.stopped ? "Ended" : "Open"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Box>
  );
}

/** The person's Microsoft 365 sign-ins, last 7 days, as rows (ADR-0038 row 27). */
export function PersonSignIns({ person }: { person: string }) {
  const t = useQuery({
    queryKey: ["person-timeline", person, 7],
    queryFn: () => api.personTimeline(person, 7),
  });
  const d = t.data;
  const filled = d ? drillSql({ sql: d.signins_sql, from: d.start, to: d.end }) : "";
  const q = useQuery<QueryResult>({
    queryKey: ["person-signins", filled],
    queryFn: () => api.query({ sql: filled, start: d?.start, end: d?.end }),
    enabled: !!d,
  });
  const err = t.error ?? q.error;
  return (
    <Box
      label="Sign-ins"
      note="Microsoft 365, last 7 days"
      action={
        d ? (
          <button
            type="button"
            onClick={() =>
              openDrill({
                sql: d.signins_sql,
                from: d.start,
                to: d.end,
                origin: `${person} > Sign-ins`,
              })
            }
            className="text-sm text-accent-text hover:underline"
          >
            Open in Search
          </button>
        ) : null
      }
    >
      {t.isLoading || q.isLoading ? (
        <div aria-busy="true" className="h-24 animate-pulse" />
      ) : err ? (
        <LoadFailed
          what="sign-ins"
          error={err}
          onRetry={() => void (t.isError ? t.refetch() : q.refetch())}
          retrying={t.isFetching || q.isFetching}
        />
      ) : q.data && q.data.row_count === 0 ? (
        <p className="px-3 py-4 text-sm text-text-secondary">
          No Microsoft 365 sign-ins by this person in the last 7 days.
        </p>
      ) : q.data ? (
        <ResultsTable result={q.data} view="parsed" compact geo={q.data.geo} />
      ) : null}
    </Box>
  );
}

/** Alerts about the person, any state (ADR-0038 row 27). */
export function PersonAlerts({ person }: { person: string }) {
  const q = useQuery({
    queryKey: ["person-alerts", person],
    queryFn: () => api.personAlerts(person),
  });
  return (
    <Box label="Alerts" note="Alerts that name this person, newest first">
      {q.isLoading ? (
        <div aria-busy="true" className="h-24 animate-pulse" />
      ) : q.isError ? (
        <LoadFailed
          what="alerts"
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
        />
      ) : !q.data?.items.length ? (
        <p className="px-3 py-4 text-sm text-text-secondary">
          No alerts name this person. Alerts raised before this version record no people.
        </p>
      ) : (
        <ul className="flex flex-col">
          {q.data.items.map((i) => (
            <li
              key={i.item_id}
              className="grid grid-cols-[8rem_minmax(0,1fr)_auto] items-baseline gap-x-3 border-b border-border px-3 py-1.5 text-sm last:border-0"
            >
              <span className="whitespace-nowrap text-text-muted">
                <When iso={i.created_at} />
              </span>
              <button
                type="button"
                onClick={() => navigate("alerts", `item=${i.item_id}`)}
                className={cn(
                  "min-w-0 truncate text-left hover:underline",
                  i.state === "open" ? "text-text" : "text-text-secondary",
                )}
              >
                {i.title}
              </button>
              <span className="text-text-secondary">
                {i.state === "open" ? "Open" : (i.close_reason_label ?? "Closed")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Box>
  );
}
