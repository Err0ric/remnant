import { useMutation, useQueryClient } from "@tanstack/react-query";
import { since, stamp } from "@/features/overview/time";
import { api, type FailingJob } from "@/lib/api";

const NAMES: Record<string, string> = {
  "ai_watch.events": "AI Watch: new AI use",
  "ai_watch.agents": "AI Watch: agent changes",
  "ai_watch.review": "AI Watch: hourly review",
};

function jobName(job: string): string {
  if (NAMES[job]) return NAMES[job]!;
  return job.startsWith("page.") ? `Page refresh: ${job.slice(5).replace(/_/g, " ")}` : job;
}

/** Background checks failing right now, for administrators (owner, 2026-11-03): since
 * when, how many runs, and why, as the server log has it (no data values). "Check AI Watch
 * now" runs every AI Watch step at once and shows which failed. */
export function BackgroundFailures({ rows, now }: { rows: FailingJob[]; now: string }) {
  const qc = useQueryClient();
  const check = useMutation({
    mutationFn: api.checkAiWatch,
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["health-checks"] });
      void qc.invalidateQueries({ queryKey: ["ai-watch-status"] });
    },
  });
  return (
    <section
      aria-label="Background checks failing"
      className="overflow-hidden rounded-card border border-warn bg-surface"
    >
      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-surface-head px-3 py-2">
        <h2 className="text-base font-semibold">Background checks failing</h2>
        <button
          type="button"
          disabled={check.isPending}
          onClick={() => check.mutate()}
          className="h-7 rounded border border-border-strong px-3 text-sm hover:bg-surface disabled:opacity-60"
        >
          {check.isPending ? "Checking AI Watch…" : "Check AI Watch now"}
        </button>
      </div>
      {rows.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-secondary">
                <th className="px-3 py-2 font-semibold">Check</th>
                <th className="px-3 py-2 font-semibold">Failing since</th>
                <th className="px-3 py-2 text-right font-semibold">Runs failed</th>
                <th className="px-3 py-2 font-semibold">Last error</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => (
                <tr key={f.job} className="border-b border-border last:border-0">
                  <td className="px-3 py-2">{jobName(f.job)}</td>
                  <td className="px-3 py-2" title={`${stamp(f.since)} UTC`}>
                    {since(f.since, now)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{f.count}</td>
                  <td className="px-3 py-2 font-mono text-text-secondary [overflow-wrap:anywhere]">
                    {f.detail ?? "No message"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {check.data ? (
        <ul aria-label="AI Watch check" className="flex flex-col gap-0.5 px-3 py-2 text-sm">
          {check.data.map((s) => (
            <li key={s.step} className={s.ok ? "text-text-secondary" : "text-sev-critical-text"}>
              {NAMES[`ai_watch.${s.step}`] ?? s.step}: {s.ok ? "worked" : s.detail}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
