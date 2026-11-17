import { About } from "@/components/About";
import { SeverityMark } from "@/components/SeverityMark";
import { useQuery } from "@tanstack/react-query";
import { api, type EntityRisk } from "@/lib/api";
import { InventoryMatches } from "./InventoryLine";
import { LEAD_COL, NAME_COL, restCol } from "./listColumns";

type Kind = "user" | "ip" | "host";

interface RiskTableProps {
  label: string;
  kind: Kind;
  rows: EntityRisk[];
  onPick: (row: EntityRisk) => void;
  /** The range's start, for the Proxmox inventory lines on address and host rows. */
  start?: string;
  /** The end of a Custom range; left out for a window that ends now. */
  end?: string;
  /** People's AI watch flags are withheld from this viewer (View people in AI usage, D242). */
  aiPeopleHidden?: boolean;
}

const LEVELS = ["critical", "high", "medium", "low"] as const;

/** What each part of the score is called, in the order the hover lists them (D195). */
export const PART_LABEL: Record<string, string> = {
  rule_matches: "Rule matches",
  flagged_runs: "Flagged schedule runs",
  failed_signins: "Failed sign-ins",
  mail_rules: "Risky inbox rules",
  consents: "App consents",
  ai_flags: "AI watch flags",
  attacks: "Attack hits",
  alerts: "Alerts",
};

const AI_FLAG_LABEL: Record<string, string> = {
  personal_account: "personal Claude account",
  unreviewed_service: "unreviewed AI service",
  new_mcp: "new MCP server",
  blocked_calls: "blocked or failed tool calls",
};

type Column = "failed_signins" | "mail_rules" | "consents" | "ai_flags" | "attacks" | "alerts";

/** The signal columns each kind has: inbox rules and consents are a person's, attack hits a
 * host's or an address's, AI flags a person's or a machine's. */
const COLUMNS: Record<Kind, Column[]> = {
  user: ["failed_signins", "mail_rules", "consents", "ai_flags", "alerts"],
  host: ["failed_signins", "attacks", "ai_flags", "alerts"],
  ip: ["failed_signins", "attacks", "alerts"],
};

/** "Rule matches 15, Failed sign-ins 25 (capped), ... = 52". */
export function scoreTitle(r: EntityRisk): string {
  const parts = Object.entries(r.parts ?? {}).filter(([, n]) => n > 0);
  if (!parts.length) return "Nothing adds to the score in this range";
  const capped = (k: string) =>
    (k === "failed_signins" && (r.failed_signins ?? 0) > 25) ||
    (k === "attacks" && (r.attacks ?? 0) > 25);
  return (
    parts.map(([k, n]) => `${PART_LABEL[k] ?? k}: ${n}${capped(k) ? " (capped)" : ""}`).join("\n") +
    `\nScore: ${r.score}`
  );
}

function Cell({ r, col, hidden }: { r: EntityRisk; col: Column; hidden: boolean }) {
  if (col === "ai_flags" && hidden) {
    return (
      <span className="font-sans text-text-muted" title="Needs View people in AI usage">
        Hidden
      </span>
    );
  }
  if (col === "ai_flags") {
    const flags = r.ai_flags ?? [];
    return (
      <span
        title={flags.map((f) => AI_FLAG_LABEL[f] ?? f).join(", ") || undefined}
        className={flags.length ? "" : "text-text-muted"}
      >
        {flags.length}
      </span>
    );
  }
  const n = r[col] ?? 0;
  return <span className={n ? "" : "text-text-muted"}>{n.toLocaleString()}</span>;
}

/** People and devices, ranked by a score whose parts each have a column and show on
 * hover (ADR-0016 row 4, D195), then by events. A row opens the person or host page. */
export function RiskTable({
  label,
  kind,
  rows,
  onPick,
  start,
  end,
  aiPeopleHidden,
}: RiskTableProps) {
  // Which Proxmox guest each address or host is (ADR-0045 A5): exact matches only.
  const values = kind === "user" ? [] : rows.slice(0, 50).map((r) => r.value);
  const inventory = useQuery({
    queryKey: ["inventory-matches", values, start, end],
    queryFn: () => api.inventoryMatches(values, start, end),
    enabled: values.length > 0,
    staleTime: 60_000,
  });
  const top = Math.max(1, ...rows.map((r) => r.score));
  const cols = COLUMNS[kind];
  // Numbers are right-aligned; headers stay on one line (listColumns.ts sets the widths).
  const NUM = "whitespace-nowrap px-3 py-2 text-right font-mono tabular-nums align-top";
  const HEAD = "whitespace-nowrap px-3 py-2 text-right";
  // Rule matches, the signal columns, and Events share what the name and score leave.
  const rest = restCol(cols.length + 2);
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-text-secondary">
            <th className={`px-3 py-2 ${NAME_COL}`}>{label}</th>
            <th aria-label="Score" className={`${HEAD} ${LEAD_COL}`}>
              <span className="flex items-center justify-end gap-1.5">
                Score
                <About
                  align="end"
                  text="10 per critical, 5 per high, 2 per medium, 1 per low rule match; 3 per flagged schedule run that names it; 1 per failed sign-in and 1 per attack hit from outside (up to 25 each); 5 per risky inbox rule; 3 per app consent; 3 per AI watch flag; 5 per alert. Only sources you may read are counted. Users are names with a successful sign-in, a Microsoft 365 identity, or an Identities link; names only ever tried in failed sign-ins are under Targeted usernames. Ranked by score, then by events."
                />
              </span>
            </th>
            <th className={HEAD} style={rest}>
              Rule matches
            </th>
            {cols.map((c) => (
              <th key={c} className={HEAD} style={rest}>
                {PART_LABEL[c]}
              </th>
            ))}
            <th className={HEAD} style={rest}>
              Events
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
              <td className="px-3 py-2 align-top">
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
                <InventoryMatches matches={inventory.data?.matches[r.value] ?? []} compact />
                {r.names && r.names.length > 1 ? (
                  <div className="text-xs text-text-muted">
                    Logged as <span className="font-mono">{r.names.join(", ")}</span>
                  </div>
                ) : null}
              </td>
              <td className="px-3 py-2 align-top">
                <div className="flex items-center justify-end gap-2" title={scoreTitle(r)}>
                  {/* A magnitude, not a severity or a state: neutral, never red
                      (docs/proposals/fix-list-2026-11-16.md item 17; DESIGN.md 6.3,
                      People & devices). */}
                  <span className="h-1.5 w-24 shrink-0 rounded bg-border-strong" aria-hidden="true">
                    <span
                      className="block h-1.5 rounded bg-text-secondary"
                      style={{ width: `${r.score ? Math.max(4, (r.score / top) * 100) : 0}%` }}
                    />
                  </span>
                  <span className="w-8 text-right font-mono tabular-nums">{r.score}</span>
                </div>
              </td>
              <td className="px-3 py-2 align-top" title={r.rules.join(", ") || undefined}>
                <div className="flex flex-wrap justify-end gap-1 whitespace-nowrap">
                  {LEVELS.map((level) =>
                    r[level] ? (
                      <SeverityMark
                        key={level}
                        tone={level}
                        label={`${r[level]} ${level}`}
                        className="text-xs"
                      />
                    ) : null,
                  )}
                  {r.flagged_runs ? (
                    <span className="rounded-badge bg-info-bg px-1.5 py-px text-xs text-info-tx">
                      {r.flagged_runs} flagged {r.flagged_runs === 1 ? "run" : "runs"}
                    </span>
                  ) : null}
                  {!r.critical && !r.high && !r.medium && !r.low && !r.flagged_runs ? (
                    <span className="font-mono text-text-muted">0</span>
                  ) : null}
                </div>
              </td>
              {cols.map((c) => (
                <td key={c} className={NUM}>
                  <Cell r={r} col={c} hidden={kind === "user" && !!aiPeopleHidden} />
                </td>
              ))}
              <td className={`${NUM} text-text-secondary`}>{r.events.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
