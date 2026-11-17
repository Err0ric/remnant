import { EmptyState } from "@/components/EmptyState";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { When } from "@/components/When";
import { fragmentValues, useSection } from "@/lib/route";
import { PageHeader } from "@/components/shell/PageHeader";
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

function lastRunText(s: Schedule): ReactNode {
  const r = s.recent[0];
  if (!r) return "Not run yet";
  const what =
    r.status === "paused"
      ? "paused"
      : r.status === "failed"
        ? "failed"
        : r.restricted
          ? "restricted"
          : `${(r.row_count ?? 0).toLocaleString()} ${r.row_count === 1 ? "row" : "rows"}${r.flagged ? " · flagged" : ""}`;
  return (
    <>
      <When iso={r.started_at} /> · {what}
    </>
  );
}

/** Scheduled saved searches and rules: create, pause, resume, run now, delete. */
export function SchedulesPage({ canCreate, isAdmin }: SchedulesPageProps) {
  const client = useQueryClient();
  const [seed] = useState(takeScheduleSeed);
  const [adding, setAdding] = useState(Boolean(seed) && canCreate);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [showLog, setShowLog] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  // `#item=<schedule id>`: the schedule a saved search links to, marked and scrolled to.
  const linked = fragmentValues(useSection()).get("item");
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: api.schedules });
  const list = schedules.data ?? [];
  const refresh = () => client.invalidateQueries({ queryKey: ["schedules"] });
  const linkedShown = Boolean(linked && list.some((s) => s.schedule_id === linked));
  useEffect(() => {
    if (!linkedShown) return;
    document.querySelector("tr[data-linked]")?.scrollIntoView?.({ block: "center" });
  }, [linkedShown, linked]);
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
        title="Schedules"
        count={`${list.length} ${list.length === 1 ? "schedule" : "schedules"}`}
        primary={
          canCreate
            ? { label: "New schedule", onClick: () => setAdding(true), disabled: adding }
            : undefined
        }
      />
      <div className="flex flex-col gap-3 px-5 py-3">
        {adding ? <ScheduleForm initial={seed} onDone={() => setAdding(false)} /> : null}
        {editing && list.find((s) => s.schedule_id === editing) ? (
          <ScheduleForm
            key={editing}
            existing={list.find((s) => s.schedule_id === editing) ?? null}
            onDone={() => setEditing(null)}
          />
        ) : null}
        {failure ? (
          <p role="alert" className="text-sm text-danger">
            {failure instanceof ApiError ? failure.message : "That did not work"}
          </p>
        ) : null}
        <section className="overflow-hidden rounded-card border border-border bg-surface">
          <div className="overflow-x-auto">
            <table aria-label="Schedules" className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-text-secondary">
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Runs</th>
                  <th className="px-3 py-2">When</th>
                  <th className="px-3 py-2">Range</th>
                  <th className="px-3 py-2">Last run</th>
                  <th className="px-3 py-2">State</th>
                  <th className="px-3 py-2">Alerts</th>
                  <th className="px-3 py-2" aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {list.map((s) => {
                  const manage = s.mine || isAdmin;
                  return (
                    <Fragment key={s.schedule_id}>
                      <tr
                        data-linked={s.schedule_id === linked ? "" : undefined}
                        aria-current={s.schedule_id === linked ? "true" : undefined}
                        className={`border-b border-border align-top last:border-0 ${
                          s.schedule_id === linked ? "bg-accent-subtle" : ""
                        }`}
                      >
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
                        <td className="px-3 py-2">
                          <div>{lastRunText(s)}</div>
                          {s.recent[0]?.definition_change ? (
                            <div className="text-text-secondary">
                              Changed: {s.recent[0].definition_change}
                            </div>
                          ) : null}
                        </td>
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
                              Next <When iso={s.next_run_at} />
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
                                onClick={() => setEditing(s.schedule_id)}
                                aria-label={`Edit ${s.name}`}
                              >
                                Edit
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
            <EmptyState
              kind="not-set-up"
              title="No schedules."
              detail="Put a saved search or a detection rule on a schedule and its results appear on the Dashboard."
            />
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
