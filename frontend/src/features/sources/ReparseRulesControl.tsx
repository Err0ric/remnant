import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { When } from "@/components/When";
import { ApiError, api, type ReparseLast, type ReparseRulesState } from "@/lib/api";

interface ReparseRulesControlProps {
  sourceId: string;
  canManage: boolean;
  /** The source list's `reparse_last`: the latest reparse job, or null. */
  last: ReparseLast | null;
}

const LABEL = "Run rules over the reparsed range";
const REMAINING = "Run the remaining rules";

function count(n: number, one: string, many: string): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

function RulesLine({ last, state }: { last: ReparseLast; state: ReparseRulesState }) {
  if (state === "running") {
    return (
      <span className="text-sm text-text-secondary">Running rules over the reparsed range…</span>
    );
  }
  if (state === "done" || state === "partial") {
    return (
      <span className="flex flex-col text-sm">
        <span className="text-text-secondary">
          Rules over the reparsed range: {count(last.rules_matched, "match", "matches")} from{" "}
          {count(last.rules_count, "rule", "rules")}, {count(last.rules_items, "alert", "alerts")}{" "}
          raised or updated, <When iso={last.rules_finished_at} />
        </span>
        {last.rules_error ? <span className="text-warn">{last.rules_error}</span> : null}
        {state === "partial" && last.rules_failed.length > 0 ? (
          <ul className="text-warn">
            {last.rules_failed.map((f) => (
              <li key={f.rule_id}>
                {f.title}: {f.error}
              </li>
            ))}
          </ul>
        ) : null}
      </span>
    );
  }
  const label =
    state === "failed"
      ? "Rules over the reparsed range failed"
      : "Rules over the reparsed range interrupted";
  return (
    <span className={`text-sm ${state === "failed" ? "text-danger" : "text-warn"}`}>
      {label}: {last.rules_error ?? ""}
    </span>
  );
}

/** Once a reparse is done (or stopped after rewriting the last waiting events), the enabled
 * rules can run over the reparsed events' time range on this source, so what they missed
 * while the template was missing becomes normal alerts, marked late (ADR-0050 row 7, D241).
 * Admins only; read from the source list, so it asks the server nothing until the admin
 * starts it. */
export function ReparseRulesControl({ sourceId, canManage, last }: ReparseRulesControlProps) {
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const run = useMutation({
    mutationFn: (jobId: string) => api.runReparseRules(sourceId, jobId),
    onSuccess: () => {
      setConfirming(false);
      void client.invalidateQueries({ queryKey: ["source-list"], exact: true });
    },
  });
  if (!canManage || !last || !last.rules_ready || !last.time_min || !last.time_max) {
    return null;
  }
  // Until the list refreshes, the start's answer says it is running.
  const started = run.data?.job_id === last.job_id ? (run.data.rules_state ?? null) : null;
  const state = last.rules_state ?? started;
  const offer =
    state === null || state === "failed" || state === "interrupted" || state === "partial";
  const label = state === "partial" ? REMAINING : LABEL;
  return (
    <span className="flex flex-col items-start gap-1 text-sm">
      {state ? <RulesLine last={last} state={state} /> : null}
      {offer && !confirming ? (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="whitespace-nowrap text-accent-text hover:underline"
        >
          {label}
        </button>
      ) : null}
      {offer && confirming ? (
        <span className="flex max-w-[22rem] flex-col gap-1.5 whitespace-normal">
          <span className="text-text-secondary">
            {state === "partial"
              ? "Run the rules that did not complete over this source's reparsed events from "
              : "Run the enabled rules over this source's reparsed events from "}
            <When iso={last.time_min} /> to <When iso={last.time_max} />. Matches become alerts
            marked Late, and each rule&apos;s usual alert targets get one &quot;Late detection from
            reparse&quot; message.
          </span>
          <span className="flex gap-2">
            <button
              type="button"
              onClick={() => run.mutate(last.job_id)}
              disabled={run.isPending}
              className="h-7 rounded bg-accent px-3 font-semibold text-white hover:brightness-110 disabled:opacity-50"
            >
              {run.isPending ? "Starting…" : label}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="h-7 rounded border border-border-strong px-3 hover:bg-surface-head"
            >
              Cancel
            </button>
          </span>
        </span>
      ) : null}
      {run.error ? (
        <span role="alert" className="text-danger">
          {run.error instanceof ApiError ? run.error.message : "Could not start the rules"}
        </span>
      ) : null}
    </span>
  );
}
