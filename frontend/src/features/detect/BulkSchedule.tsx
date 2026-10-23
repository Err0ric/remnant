import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, api, type SigmaRule } from "@/lib/api";

interface BulkScheduleProps {
  rules: SigmaRule[];
  onDone: () => void;
}

const HOW_OFTEN = [
  { cron: "hourly", label: "Every hour" },
  { cron: "daily", label: "Every day at 07:00" },
  { cron: "weekdays", label: "Weekdays at 07:00" },
];
const RANGES = [
  { value: "", label: "Since the last run" },
  { value: "60", label: "Last hour" },
  { value: "1440", label: "Last 24 hours" },
];

interface Outcome {
  made: string[];
  skipped: { title: string; why: string }[];
  failed: { title: string; why: string }[];
}

/** One schedule per selected rule, from one set of settings (F58). Each is created and
 * audited like a single schedule; rules that are off or already scheduled by you are
 * skipped and named. */
export function BulkSchedule({ rules, onDone }: BulkScheduleProps) {
  const client = useQueryClient();
  const targets = useQuery({ queryKey: ["alert-targets"], queryFn: api.alertTargets });
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: api.schedules });
  const [cron, setCron] = useState("hourly");
  const [lookback, setLookback] = useState("");
  const [targetIds, setTargetIds] = useState<string[]>([]);
  const [panels, setPanels] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Outcome | null>(null);

  const already = new Set(
    (schedules.data ?? []).filter((s) => s.kind === "rule" && s.mine).map((s) => s.target_id),
  );
  const off = rules.filter((r) => !r.enabled);
  const scheduled = rules.filter((r) => r.enabled && already.has(r.rule_id));
  const todo = rules.filter((r) => r.enabled && !already.has(r.rule_id));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    const out: Outcome = {
      made: [],
      skipped: [
        ...off.map((r) => ({ title: r.title, why: "not enabled" })),
        ...scheduled.map((r) => ({ title: r.title, why: "you already schedule it" })),
      ],
      failed: [],
    };
    for (const r of todo) {
      try {
        await api.createSchedule({
          kind: "rule",
          target_id: r.rule_id,
          cron,
          lookback_minutes: lookback ? Number(lookback) : null,
          target_ids: targetIds,
          add_panel: panels,
        });
        out.made.push(r.title);
      } catch (err) {
        out.failed.push({
          title: r.title,
          why: err instanceof ApiError ? err.message : "That did not work",
        });
      }
    }
    setBusy(false);
    setDone(out);
    await client.invalidateQueries({ queryKey: ["schedules"] });
    if (panels) await client.invalidateQueries({ queryKey: ["dashboards"] });
  };

  const input = "h-8 rounded border border-border bg-inset px-2";
  if (done)
    return (
      <section
        aria-label="Schedule selected rules"
        className="flex flex-col gap-2 rounded-card border border-border bg-surface p-3 text-sm"
      >
        <p role="status">
          Scheduled {done.made.length} {done.made.length === 1 ? "rule" : "rules"}.
          {done.skipped.length ? ` Skipped ${done.skipped.length}.` : ""}
          {done.failed.length ? ` ${done.failed.length} failed.` : ""}
        </p>
        {[...done.skipped, ...done.failed].length ? (
          <ul className="text-text-secondary">
            {done.skipped.map((s) => (
              <li key={s.title}>
                {s.title}: {s.why}
              </li>
            ))}
            {done.failed.map((s) => (
              <li key={s.title} className="text-danger">
                {s.title}: {s.why}
              </li>
            ))}
          </ul>
        ) : null}
        <div>
          <button
            type="button"
            onClick={onDone}
            className="h-8 rounded border border-border-strong px-3 hover:bg-surface-head"
          >
            Close
          </button>
        </div>
      </section>
    );
  return (
    <form
      aria-label="Schedule selected rules"
      onSubmit={(e) => void submit(e)}
      className="flex flex-col gap-3 rounded-card border border-border bg-surface p-3 text-sm"
    >
      <h2 className="font-semibold">
        Schedule {todo.length} selected {todo.length === 1 ? "rule" : "rules"}
      </h2>
      {off.length || scheduled.length ? (
        <p className="text-text-secondary">
          {[
            off.length ? `${off.length} not enabled` : "",
            scheduled.length ? `${scheduled.length} you already schedule` : "",
          ]
            .filter(Boolean)
            .join(", ")}{" "}
          will be skipped.
        </p>
      ) : null}
      <div className="flex flex-wrap gap-4">
        <label className="flex flex-col gap-1">
          <span className="text-text-secondary">How often</span>
          <select className={input} value={cron} onChange={(e) => setCron(e.target.value)}>
            {HOW_OFTEN.map((o) => (
              <option key={o.cron} value={o.cron}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-text-secondary">Each run looks at</span>
          <select className={input} value={lookback} onChange={(e) => setLookback(e.target.value)}>
            {RANGES.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <fieldset className="flex flex-col gap-1">
        <legend className="mb-1 text-text-secondary">Send alerts to</legend>
        {(targets.data ?? []).length ? (
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {(targets.data ?? []).map((t) => (
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
        <span className="text-text-muted">An alert goes out when a run finds matches.</span>
      </fieldset>
      <label className="flex items-center gap-1.5">
        <input type="checkbox" checked={panels} onChange={(e) => setPanels(e.target.checked)} />
        Also add a panel for each to my dashboard (matches show on Health either way)
      </label>
      <p className="text-text-secondary">
        One schedule per rule, each running as you and each in the audit log.
      </p>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={!todo.length || busy}
          className="h-8 rounded bg-accent px-3 font-semibold text-white hover:brightness-110 disabled:opacity-40"
        >
          {busy ? "Scheduling…" : `Schedule ${todo.length} ${todo.length === 1 ? "rule" : "rules"}`}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="h-8 rounded border border-border-strong px-3 hover:bg-surface-head"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
