import type { TargetedUsername } from "@/lib/api";
import { LEAD_COL, NAME_COL, restCol } from "./listColumns";

interface TargetedTableProps {
  rows: TargetedUsername[];
  onPick: (row: TargetedUsername) => void;
}

/** "Netherlands 6, Brazil 3"; nothing when enrichment is off. */
function places(list: { label: string; attempts: number }[]): string {
  return list.map((p) => `${p.label} ${p.attempts.toLocaleString()}`).join(", ");
}

/** Usernames tried in failed sign-ins that are nobody's (D212), most attempted first. A
 * row opens the same page a user does. */
export function TargetedTable({ rows, onPick }: TargetedTableProps) {
  const CELL = "px-3 py-2 align-top";
  // The same column scheme as the other tabs, so they line up when switching.
  const rest = restCol(4);
  return (
    <div className="overflow-x-auto">
      <table aria-label="Targeted usernames" className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-text-secondary">
            <th className={`px-3 py-2 ${NAME_COL}`}>Username</th>
            <th className={`whitespace-nowrap px-3 py-2 text-right ${LEAD_COL}`}>Attempts</th>
            <th className="whitespace-nowrap px-3 py-2" style={rest}>
              Sources
            </th>
            <th className="whitespace-nowrap px-3 py-2" style={rest}>
              Top countries
            </th>
            <th className="whitespace-nowrap px-3 py-2" style={rest}>
              Top networks (ASN)
            </th>
            <th className="whitespace-nowrap px-3 py-2" style={rest}>
              Hosts targeted
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.value}
              className="cursor-pointer border-b border-border last:border-b-0 hover:bg-surface-head"
              onClick={() => onPick(r)}
            >
              <td className={CELL}>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onPick(r);
                  }}
                  className="text-left font-mono text-accent-text [overflow-wrap:anywhere] hover:underline"
                >
                  {r.value}
                </button>
              </td>
              <td className={`${CELL} whitespace-nowrap text-right font-mono tabular-nums`}>
                {r.attempts.toLocaleString()}
              </td>
              <td className={`${CELL} font-mono text-text-secondary`}>{r.sources.join(", ")}</td>
              <td className={CELL}>{places(r.countries)}</td>
              <td className={CELL}>{places(r.asns)}</td>
              <td className={`${CELL} font-mono text-text-secondary`} title={r.hosts.join(", ")}>
                {r.hosts.slice(0, 3).join(", ")}
                {r.hosts.length > 3 ? ` +${r.hosts.length - 3} more` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
