import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Command, PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api, type Schedule } from "@/lib/api";
import { takeScheduleSeed } from "@/lib/scheduleSeed";
import { DeliveryLog } from "./DeliveryLog";
import { ScheduleForm } from "./ScheduleForm";
import { cronLabel, lookbackLabel } from "./schedule";

interface SchedulesPageProps {
  /** Admins and analysts create schedules; auditors only view (SPEC 5.5). */
  canCreate: boolean;
  isAdmin: boolean;
}

function lastRunText(s: Schedule): string {
  const r = s.recent[0];
  if (!r) return "Not run yet";
  const when = r.started_at.slice(0, 16).replace("T", " ");
  if (r.status === "paused") return `${when} · paused`;
  if (r.status === "failed") return `${when} · failed`;
  if (r.restricted) return `${when} · restricted`;
  return `${when} · ${r.row_count ?? 0} rows${r.flagged ? " · flagged" : ""}`;
}

/** Scheduled saved searches and rules: create, pause, resume, run now, delete. */
export function SchedulesPage({ canCreate, isAdmin }: SchedulesPageProps) {
  const client = useQueryClient();
  const [seed] = useState(takeScheduleSeed);
  const [adding, setAdding] = useState(Boolean(seed) && canCreate);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [showLog, setShowLog] = useState<string | null>(null);
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: api.schedules });
  const list = schedules.data ?? [];
  const refresh = () => client.invalidateQueries({ queryKey: ["schedules"] });
  const pause = useMutation({
    mutationFn: (s: Schedule) => api.updateSchedule(s.schedule_id, { paused: !s.paused }),
    onSuccess: refresh,
  });
  const runNow = useMutation({
    mutationFn: (s: Schedule) => api.runSchedule(s.schedule_id),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteSchedule(id),
    onSuccess: async () => {
      setConfirmDelete(null);
      await refresh();
    },
  });
  const failure = [schedules.error, pause.error, runNow.error, remove.error].find(Boolean);
  const btn = "rounded px-2 py-0.5 hover:bg-surface-head disabled:opacity-40";

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        crumbs={["Home", "Detect", "Schedules"]}
        title="Schedules"
        meta={`${list.length} ${list.length === 1 ? "schedule" : "schedules"}`}
        commands={
          canCreate ? (
            <Command
              label="New schedule"
              primary
              onClick={() => setAdding(true)}
              disabled={adding}
            />
          ) : null
        }
      />
      <div className="flex flex-col gap-3 px-5 py-3">
        {adding ? <ScheduleForm initial={seed} onDone={() => setAdding(false)} /> : null}
        {failure ? (
          <p role="alert" className="text-sm text-danger">
            {failure instanceof ApiError ? failure.message : "That did not work"}
          </p>
        ) : null}
        <section className="overflow-hidden rounded-card border border-border bg-surface">
          <div className="overflow-x-auto">
            <table aria-label="Schedules" className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
                  <th className="px-3 py-2 font-semibold">Name</th>
                  <th className="px-3 py-2 font-semibold">Runs</th>
                  <th className="px-3 py-2 font-semibold">When</th>
                  <th className="px-3 py-2 font-semibold">Range</th>
                  <th className="px-3 py-2 font-semibold">Last run</th>
                  <th className="px-3 py-2 font-semibold">State</th>
                  <th className="px-3 py-2 font-semibold">Alerts</th>
                  <th className="px-3 py-2" aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {list.map((s) => {
                  const manage = s.mine || isAdmin;
                  return (
                    <Fragment key={s.schedule_id}>
                      <tr className="border-b border-border align-top last:border-0">
                        <td className="px-3 py-2">
                          <div className="font-semibold">{s.name}</div>
                          <div className="text-text-muted">
                            {s.mine ? "Yours" : "Someone else's"}
                            {s.shared ? " · shared" : ""}
                          </div>
                        </td>
                        <td className="px-3 py-2">
                          {s.kind === "search" ? "Saved search" : "Rule"}
                        </td>
                        <td className="px-3 py-2">{cronLabel(s.cron)}</td>
                        <td className="px-3 py-2">{lookbackLabel(s.lookback_minutes)}</td>
                        <td className="px-3 py-2 font-mono">{lastRunText(s)}</td>
                        <td className="px-3 py-2">
                          {s.paused ? (
                            <>
                              <span className="text-warn">Paused</span>
                              {s.paused_reason ? (
                                <div className="text-text-secondary">{s.paused_reason}</div>
                              ) : null}
                            </>
                          ) : (
                            <span>
                              Next{" "}
                              {s.next_run_at ? s.next_run_at.slice(0, 16).replace("T", " ") : "·"}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <button
                            type="button"
                            className={btn}
                            aria-expanded={showLog === s.schedule_id}
                            onClick={() =>
                              setShowLog(showLog === s.schedule_id ? null : s.schedule_id)
                            }
                            aria-label={`Alerts of ${s.name}`}
                          >
                            {s.target_ids.length
                              ? `${s.target_ids.length} ${s.target_ids.length === 1 ? "target" : "targets"}`
                              : "None"}
                          </button>
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right">
                          {manage ? (
                            <>
                              <button
                                type="button"
                                className={btn}
                                disabled={s.paused || runNow.isPending}
                                onClick={() => runNow.mutate(s)}
                                aria-label={`Run ${s.name} now`}
                              >
                                Run now
                              </button>
                              <button
                                type="button"
                                className={btn}
                                onClick={() => pause.mutate(s)}
                                aria-label={`${s.paused ? "Resume" : "Pause"} ${s.name}`}
                              >
                                {s.paused ? "Resume" : "Pause"}
                              </button>
                              {confirmDelete === s.schedule_id ? (
                                <>
                                  <button
                                    type="button"
                                    className={`${btn} font-semibold text-danger`}
                                    onClick={() => remove.mutate(s.schedule_id)}
                                  >
                                    Confirm delete
                                  </button>
                                  <button
                                    type="button"
                                    className={btn}
                                    onClick={() => setConfirmDelete(null)}
                                  >
                                    Keep
                                  </button>
                                </>
                              ) : (
                                <button
                                  type="button"
                                  className={btn}
                                  onClick={() => setConfirmDelete(s.schedule_id)}
                                  aria-label={`Delete ${s.name}`}
                                >
                                  Delete
                                </button>
                              )}
                            </>
                          ) : null}
                        </td>
                      </tr>
                      {showLog === s.schedule_id ? (
                        <tr className="border-b border-border bg-surface-expand">
                          <td colSpan={8} className="px-3 py-2">
                            <DeliveryLog scheduleId={s.schedule_id} />
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          {list.length === 0 && schedules.isSuccess ? (
            <p className="px-3 py-8 text-center text-sm text-text-secondary">
              No schedules. Put a saved search or a detection rule on a schedule and its results
              appear on the Dashboard.
            </p>
          ) : null}
        </section>
        <p className="text-xs text-text-muted">
          Resuming a paused schedule accepts whatever changed (the saved search, or the sources the
          owner can read), so check it first.
        </p>
      </div>
    </div>
  );
}
