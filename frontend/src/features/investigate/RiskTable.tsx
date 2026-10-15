import type { EntityRisk } from "@/lib/api";

interface RiskTableProps {
  label: string;
  rows: EntityRisk[];
  onPick: (row: EntityRisk) => void;
}

const LEVELS = [
  ["critical", "bg-sev-critical-bg text-sev-critical-text"],
  ["high", "bg-sev-high-bg text-sev-high-text"],
  ["medium", "bg-sev-medium-bg text-sev-medium-text"],
  ["low", "bg-sev-low-bg text-sev-low-text"],
] as const;

/** Most active entities, ranked by score; the score is shown with the parts it is made
 * of (ADR-0016 row 4). A row opens the entity in lanes. */
export function RiskTable({ label, rows, onPick }: RiskTableProps) {
  const top = Math.max(1, ...rows.map((r) => r.score));
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
            <th className="px-3 py-2 font-semibold">{label}</th>
            <th className="px-3 py-2 font-semibold">Rule matches</th>
            <th className="px-3 py-2 font-semibold">Rules</th>
            <th className="w-40 px-3 py-2 text-right font-semibold">Score</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.value}
              className="cursor-pointer border-b border-border last:border-b-0 hover:bg-surface-head"
              onClick={() => onPick(r)}
            >
              <td className="px-3 py-2 align-top">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onPick(r);
                  }}
                  className="break-all text-left font-mono text-accent-text hover:underline"
                >
                  {r.value}
                </button>
                {r.names && r.names.length > 1 ? (
                  <div className="text-xs text-text-muted">
                    Logged as <span className="font-mono">{r.names.join(", ")}</span>
                  </div>
                ) : null}
              </td>
              <td className="px-3 py-2 align-top">
                <div className="flex flex-wrap gap-1">
                  {LEVELS.map(([level, tint]) =>
                    r[level] ? (
                      <span
                        key={level}
                        className={`rounded-badge px-1.5 py-px text-xs font-semibold ${tint}`}
                      >
                        {r[level]} {level}
                      </span>
                    ) : null,
                  )}
                  {r.flagged_runs ? (
                    <span className="rounded-badge bg-sev-info-bg px-1.5 py-px text-xs text-sev-info-text">
                      {r.flagged_runs} flagged {r.flagged_runs === 1 ? "run" : "runs"}
                    </span>
                  ) : null}
                </div>
              </td>
              <td className="max-w-md px-3 py-2 align-top text-text-secondary">
                {r.rules.join(", ")}
              </td>
              <td className="px-3 py-2 align-top">
                <div className="flex items-center justify-end gap-2">
                  <span className="h-1.5 w-24 rounded bg-surface-head" aria-hidden="true">
                    <span
                      className="block h-1.5 rounded bg-danger"
                      style={{ width: `${Math.max(4, (r.score / top) * 100)}%` }}
                    />
                  </span>
                  <span className="w-8 text-right font-mono tabular-nums">{r.score}</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
