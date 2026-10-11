import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, type ScheduleInput, type ThresholdKind } from "@/lib/api";
import { PRESETS } from "./schedule";

interface ScheduleFormProps {
  onDone: () => void;
  /** Preselected target, from a "Schedule" button elsewhere. */
  initial?: { kind: "search" | "rule"; targetId: string } | null;
}

const LOOKBACKS = [
  { value: "", label: "Since the last run" },
  { value: "60", label: "Last hour" },
  { value: "1440", label: "Last 24 hours" },
  { value: "10080", label: "Last 7 days" },
];

/** New schedule for a saved search or an enabled rule (SPEC 5.5). Runs as you. */
export function ScheduleForm({ onDone, initial = null }: ScheduleFormProps) {
  const client = useQueryClient();
  const [kind, setKind] = useState<"search" | "rule">(initial?.kind ?? "search");
  const [target, setTarget] = useState(initial?.targetId ?? "");
  const [name, setName] = useState("");
  const [preset, setPreset] = useState<string>("daily");
  const [cron, setCron] = useState("");
  const [lookback, setLookback] = useState("");
  const [shared, setShared] = useState(false);
  const [thresholdKind, setThresholdKind] = useState<ThresholdKind | "">("");
  const [thresholdValue, setThresholdValue] = useState("");
  const [targetIds, setTargetIds] = useState<string[]>([]);
  const alertTargets = useQuery({ queryKey: ["alert-targets"], queryFn: api.alertTargets });
  const searches = useQuery({ queryKey: ["searches"], queryFn: api.searches });
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules, enabled: kind === "rule" });
  const targets =
    kind === "search"
      ? (searches.data ?? []).map((s) => ({ id: s.id, label: s.name }))
      : (rules.data ?? []).filter((r) => r.enabled).map((r) => ({ id: r.rule_id, label: r.title }));

  const save = useMutation({
    mutationFn: () => {
      const body: ScheduleInput = {
        kind,
        target_id: target,
        cron: preset === "custom" ? cron.trim() : preset,
        lookback_minutes: lookback ? Number(lookback) : null,
        shared,
      };
      if (targetIds.length) body.target_ids = targetIds;
      if (name.trim()) body.name = name.trim();
      if (thresholdKind && thresholdValue !== "") {
        body.threshold_kind = thresholdKind;
        body.threshold_value = Number(thresholdValue);
      }
      return api.createSchedule(body);
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["schedules"] });
      onDone();
    },
  });

  const field = "flex min-w-0 flex-col gap-1 text-sm";
  const input = "h-8 rounded border border-border bg-inset px-2";
  return (
    <form
      aria-label="New schedule"
      className="flex flex-col gap-3 rounded-card border border-border bg-surface p-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (target) save.mutate();
      }}
    >
      <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
        <label className={field}>
          <span className="text-text-secondary">Runs</span>
          <select
            className={input}
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as "search" | "rule");
              setTarget("");
            }}
          >
            <option value="search">A saved search</option>
            <option value="rule">A detection rule</option>
          </select>
        </label>
        <label className={field}>
          <span className="text-text-secondary">{kind === "search" ? "Saved search" : "Rule"}</span>
          <select className={input} value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">Choose…</option>
            {targets.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label className={field}>
          <span className="text-text-secondary">Name (optional)</span>
          <input className={input} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className={field}>
          <span className="text-text-secondary">When</span>
          <select className={input} value={preset} onChange={(e) => setPreset(e.target.value)}>
            {PRESETS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
            <option value="custom">Custom cron…</option>
          </select>
        </label>
        {preset === "custom" ? (
          <label className={field}>
            <span className="text-text-secondary">Cron (minute hour day month weekday)</span>
            <input
              className={`${input} font-mono`}
              value={cron}
              placeholder="*/15 * * * *"
              onChange={(e) => setCron(e.target.value)}
            />
          </label>
        ) : null}
        <label className={field}>
          <span className="text-text-secondary">Time range of each run</span>
          <select className={input} value={lookback} onChange={(e) => setLookback(e.target.value)}>
            {LOOKBACKS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
        <label className={field}>
          <span className="text-text-secondary">Flag a run when the count is</span>
          <div className="flex gap-2">
            <select
              aria-label="Flag when"
              className={`${input} min-w-0 flex-1`}
              value={thresholdKind}
              onChange={(e) => setThresholdKind(e.target.value as ThresholdKind | "")}
            >
              <option value="">Never</option>
              <option value="above">Above</option>
              <option value="below">Below</option>
              <option value="change_pct">Changed by more than (%)</option>
            </select>
            {thresholdKind ? (
              <input
                aria-label="Flag value"
                type="number"
                min={0}
                className={`${input} w-24`}
                value={thresholdValue}
                onChange={(e) => setThresholdValue(e.target.value)}
              />
            ) : null}
          </div>
        </label>
      </div>
      <fieldset className="flex flex-col gap-1 text-sm">
        <legend className="mb-1 text-text-secondary">Send alerts to</legend>
        {(alertTargets.data ?? []).length ? (
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {(alertTargets.data ?? []).map((t) => (
              <label key={t.target_id} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={targetIds.includes(t.target_id)}
                  onChange={(e) =>
                    setTargetIds((prev) =>
                      e.target.checked
                        ? [...prev, t.target_id]
                        : prev.filter((id) => id !== t.target_id),
                    )
                  }
                />
                {t.name}
              </label>
            ))}
          </div>
        ) : (
          <span className="text-text-muted">No alert targets yet; an admin can add them.</span>
        )}
        <span className="text-text-muted">
          Alerts go out when a run is flagged, when a rule schedule without a flag finds matches,
          and when the schedule pauses itself.
        </span>
      </fieldset>
      <label className="flex items-center gap-1.5 text-sm">
        <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} />
        Shared: other people see it on their dashboard (only runs on sources they can read)
      </label>
      <p className="text-sm text-text-secondary">
        Runs as you, with your access checked every run. If the saved search changes, the rule is
        disabled, or you lose access to a source, it pauses until you resume it.
      </p>
      {save.error ? (
        <p role="alert" className="text-sm text-danger">
          {save.error instanceof ApiError ? save.error.message : "That did not work"}
        </p>
      ) : null}
      <div className="flex gap-2">
        <button
          type="submit"
          className="h-8 rounded bg-accent px-3 font-semibold text-white disabled:opacity-40"
          disabled={!target || save.isPending}
        >
          Create schedule
        </button>
        <button type="button" className="h-8 rounded px-3 hover:bg-surface-head" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  );
}
