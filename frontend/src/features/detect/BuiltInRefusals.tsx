import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { openDrill } from "@/lib/drill";

const ROWS =
  "SELECT time, message AS refused, actor_user_name, status_detail AS reason, src_endpoint_ip," +
  " event_id\nFROM events\nWHERE template_id = 'server_events'\n" +
  "  AND coalesce(time, time_observed) >= TIMESTAMPTZ '{from}'" +
  " AND coalesce(time, time_observed) < TIMESTAMPTZ '{to}'\n" +
  "ORDER BY coalesce(time, time_observed) DESC";

/** The built-in detection that protects this server (ADR-0040): refused ingest tokens,
 * sign-ins, single sign-on, and API tokens from one address. On by default. */
export function BuiltInRefusals({ isAdmin }: { isAdmin: boolean }) {
  const client = useQueryClient();
  const q = useQuery({ queryKey: ["refusal-rule"], queryFn: api.refusalRule });
  const [threshold, setThreshold] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (v: { enabled: boolean; threshold: number }) => api.setRefusalRule(v),
    onSuccess: () => {
      setThreshold(null);
      void client.invalidateQueries({ queryKey: ["refusal-rule"] });
    },
  });
  const d = q.data;
  if (!d) return null;
  const n = Number(threshold ?? d.threshold);
  const now = new Date();
  return (
    <section
      aria-label="Built-in detection"
      className="flex flex-col gap-1.5 rounded-card border border-border bg-surface px-3 py-2.5 text-sm"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="font-semibold">Refused credentials from one address</h2>
        <span className="rounded-badge bg-surface-head px-1.5 py-px text-xs text-text-secondary">
          Built in
        </span>
        <span className={d.enabled ? "text-ok" : "text-text-muted"}>
          {d.enabled ? "On" : "Off"}
        </span>
        <button
          type="button"
          onClick={() =>
            openDrill({
              sql: ROWS,
              from: new Date(now.getTime() - 86_400_000).toISOString(),
              to: now.toISOString(),
              origin: "Alerts > Rules > Refused credentials, last 24 hours",
            })
          }
          className="ml-auto text-accent-text hover:underline"
        >
          Open refusals in Search
        </button>
      </div>
      <p className="text-text-secondary">
        Raises a High alert when one address has {d.threshold} or more refused ingest tokens,
        sign-ins, single sign-on attempts, or API tokens in {d.window_minutes} minutes: a sign of
        someone guessing. The events are in the server_events source; no token or password is kept.
      </p>
      {isAdmin ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate({ enabled: d.enabled, threshold: n });
          }}
        >
          <label className="flex items-center gap-2">
            Threshold
            <input
              type="number"
              min={3}
              max={1000}
              value={threshold ?? String(d.threshold)}
              onChange={(e) => setThreshold(e.target.value)}
              className="h-7 w-24 rounded border border-border bg-inset px-2 tabular-nums"
            />
          </label>
          {threshold !== null ? (
            <button type="submit" className="text-accent-text hover:underline">
              Save
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => save.mutate({ enabled: !d.enabled, threshold: d.threshold })}
            className="text-accent-text hover:underline"
          >
            {d.enabled ? "Turn off" : "Turn on"}
          </button>
          {save.error ? (
            <span role="alert" className="text-danger">
              {save.error instanceof ApiError ? save.error.message : "Could not save"}
            </span>
          ) : null}
        </form>
      ) : null}
    </section>
  );
}
