import type { Overview } from "@/lib/api";
import { navigate } from "@/lib/route";
import { since } from "@/features/overview/time";

interface StatusLineProps {
  overview: Overview;
  now: string;
}

/** Detections, paused schedules, and alert delivery (F55): one line when all is clear,
 * a short list for whichever has something. */
export function StatusLine({ overview: o, now }: StatusLineProps) {
  // One line per detection: runs of the same rule or search grouped, newest first.
  const grouped = new Map<
    string,
    { d: (typeof o.detections)[number]; runs: number; total: number }
  >();
  for (const d of o.detections) {
    const key = `${d.kind}:${d.schedule_id ?? d.name}`;
    const g = grouped.get(key);
    if (g) {
      g.runs += 1;
      g.total += d.count;
    } else grouped.set(key, { d, runs: 1, total: d.count });
  }
  const failing = (o.alerts?.targets ?? []).filter((t) => t.failing);
  const failed = o.alerts?.failed_deliveries ?? 0;
  const delivery = o.alerts ? failed > 0 || failing.length > 0 : false;
  if (!o.detections.length && !o.paused.length && !delivery)
    return (
      <p className="rounded-card border border-border bg-surface px-3 py-2 text-sm text-text-secondary">
        No detections in 24 hours. No paused schedules.
        {o.alerts ? " Every alert was delivered." : ""}
      </p>
    );
  return (
    <section
      aria-label="Detections and schedules"
      className="grid grid-cols-1 gap-x-6 gap-y-2 rounded-card border border-border bg-surface px-3 py-2 text-sm md:grid-cols-3"
    >
      <div className="min-w-0">
        <h2 className="font-semibold">
          Detections, 24 hours{" "}
          <span className="font-normal text-text-muted">{o.detections.length}</span>
        </h2>
        {o.detections.length ? (
          <ul>
            {[...grouped.values()].slice(0, 5).map(({ d, runs, total }) => (
              <li key={d.run_id} className="flex gap-2">
                <button
                  type="button"
                  onClick={() => navigate(d.kind === "rule" ? "rules" : "dashboard")}
                  className="min-w-0 truncate text-left text-accent-text hover:underline"
                >
                  {d.name}
                </button>
                <span className="ml-auto shrink-0 text-text-secondary">
                  <span className="font-mono tabular-nums">{total.toLocaleString()}</span>
                  {runs > 1 ? ` in ${runs} runs` : ""}, latest {since(d.started_at, now)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-text-secondary">None</p>
        )}
      </div>
      <div className="min-w-0">
        <h2 className="font-semibold">
          Paused schedules <span className="font-normal text-text-muted">{o.paused.length}</span>
        </h2>
        {o.paused.length ? (
          <ul>
            {o.paused.map((p) => (
              <li key={p.schedule_id} className="[overflow-wrap:anywhere]">
                <button
                  type="button"
                  onClick={() => navigate("schedules")}
                  className="text-left text-accent-text hover:underline"
                >
                  {p.name}
                </button>
                {p.reason ? <span className="text-text-secondary">: {p.reason}</span> : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-text-secondary">None</p>
        )}
      </div>
      {o.alerts ? (
        <div className="min-w-0">
          <h2 className="font-semibold">Alert delivery</h2>
          {delivery ? (
            <ul>
              {failing.map((t) => (
                <li key={t.target_id} className="text-danger [overflow-wrap:anywhere]">
                  {t.name}: {t.consecutive_failures} failed in a row
                  {t.last_error ? ` (${t.last_error})` : ""}
                </li>
              ))}
              {failed && !failing.length ? (
                <li className="text-warn">{failed} failed in 24 hours, then delivered</li>
              ) : null}
            </ul>
          ) : (
            <p className="text-text-secondary">Every alert was delivered</p>
          )}
        </div>
      ) : null}
    </section>
  );
}
