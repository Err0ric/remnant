import type { SigmaRule, SigmaRuleListed } from "@/lib/api";
import { LevelBadge } from "./LevelBadge";
import { authorText, logsourceText } from "./rules";

interface RulesTableProps {
  rules: SigmaRuleListed[];
  isAdmin: boolean;
  canRun: boolean;
  selected: Set<string>;
  runningId: string | null;
  onToggle: (ruleId: string) => void;
  onToggleAll: (checked: boolean) => void;
  onRun: (rule: SigmaRule) => void;
  onView: (rule: SigmaRule) => void;
  onSchedule: (rule: SigmaRule) => void;
}

export function RulesTable({
  rules,
  isAdmin,
  canRun,
  selected,
  runningId,
  onToggle,
  onToggleAll,
  onRun,
  onView,
  onSchedule,
}: RulesTableProps) {
  const allChecked = rules.length > 0 && rules.every((r) => selected.has(r.rule_id));
  return (
    <div className="overflow-x-auto">
      <table aria-label="Detection rules" className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
            {isAdmin ? (
              <th className="w-8 px-3 py-2">
                <input
                  type="checkbox"
                  aria-label="Select all shown"
                  checked={allChecked}
                  onChange={(e) => onToggleAll(e.target.checked)}
                />
              </th>
            ) : null}
            <th className="px-3 py-2 font-semibold">Title</th>
            <th className="px-3 py-2 font-semibold">Level</th>
            <th className="px-3 py-2 font-semibold">Log source</th>
            <th className="px-3 py-2 font-semibold">Author</th>
            <th className="px-3 py-2 font-semibold">Sources</th>
            <th className="px-3 py-2 font-semibold">State</th>
            <th className="px-3 py-2" aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {rules.map((r) => {
            const runnable = canRun && (r.enabled || isAdmin);
            return (
              <tr key={r.rule_id} className="h-[var(--row-h)] border-b border-border last:border-0">
                {isAdmin ? (
                  <td className="px-3 py-1">
                    <input
                      type="checkbox"
                      aria-label={`Select ${r.title}`}
                      checked={selected.has(r.rule_id)}
                      onChange={() => onToggle(r.rule_id)}
                    />
                  </td>
                ) : null}
                <td className="px-3 py-1">{r.title}</td>
                <td className="px-3 py-1">
                  <LevelBadge level={r.level} />
                </td>
                <td className="px-3 py-1 font-mono text-text-secondary">{logsourceText(r)}</td>
                <td
                  className="max-w-[16rem] truncate px-3 py-1 text-text-secondary"
                  title={r.author}
                >
                  {authorText(r.author)}
                </td>
                <td
                  className="max-w-[12rem] truncate px-3 py-1 font-mono"
                  title={r.source_ids.join(", ")}
                >
                  {r.source_ids.length ? (
                    r.source_ids.join(", ")
                  ) : (
                    <span className="font-sans text-text-muted">no data</span>
                  )}
                </td>
                <td className="px-3 py-1">
                  {r.enabled ? "Enabled" : <span className="text-text-muted">Disabled</span>}
                </td>
                <td className="whitespace-nowrap px-3 py-1 text-right">
                  {canRun ? (
                    <button
                      type="button"
                      className="rounded px-2 py-0.5 hover:bg-surface-head disabled:opacity-40"
                      onClick={() => onRun(r)}
                      disabled={!runnable || runningId !== null}
                      title={runnable ? undefined : "An administrator must enable this rule first"}
                      aria-label={`Run ${r.title}`}
                    >
                      {runningId === r.rule_id ? "Running…" : "Run"}
                    </button>
                  ) : null}
                  {canRun && r.enabled ? (
                    <button
                      type="button"
                      className="rounded px-2 py-0.5 hover:bg-surface-head"
                      onClick={() => onSchedule(r)}
                      aria-label={`Schedule ${r.title}`}
                    >
                      Schedule
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="rounded px-2 py-0.5 hover:bg-surface-head"
                    onClick={() => onView(r)}
                    aria-label={`View ${r.title}`}
                  >
                    View
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
