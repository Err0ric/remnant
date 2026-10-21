import type { RuleRun } from "@/lib/api";
import { authorText } from "./rules";

interface RecentRunsProps {
  runs: RuleRun[];
  onOpen: (run: RuleRun) => void;
}

/** Runs the caller can see (only those whose sources they may read), newest first. */
export function RecentRuns({ runs, onOpen }: RecentRunsProps) {
  if (!runs.length) return null;
  return (
    <section className="overflow-hidden rounded-card border border-border bg-surface">
      <div className="border-b border-border bg-surface-head px-3 py-1.5 text-sm font-semibold">
        Recent runs
      </div>
      <div className="max-h-56 overflow-auto">
        <table aria-label="Recent runs" className="w-full text-sm">
          <tbody>
            {runs.map((r) => (
              <tr key={r.run_id} className="border-b border-border last:border-0">
                <td className="whitespace-nowrap px-3 py-1 font-mono text-text-secondary">
                  {r.started_at.slice(0, 19).replace("T", " ")}
                </td>
                <td className="px-3 py-1">
                  {r.title} <span className="text-text-muted">by {authorText(r.author)}</span>
                </td>
                <td className="whitespace-nowrap px-3 py-1 text-right font-mono">
                  {r.status === "ok"
                    ? r.match_count
                    : r.status === "no_data"
                      ? "no data"
                      : "failed"}
                </td>
                <td className="px-3 py-1 text-right">
                  <button
                    type="button"
                    className="rounded px-2 py-0.5 hover:bg-surface-head"
                    onClick={() => onOpen(r)}
                    aria-label={`Open run of ${r.title}`}
                  >
                    Open
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
