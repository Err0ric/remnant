import type { EntityRisk } from "@/lib/api";

type Kind = "user" | "ip" | "host";

interface RiskTableProps {
  label: string;
  kind: Kind;
  rows: EntityRisk[];
  onPick: (row: EntityRisk) => void;
}

const LEVELS = [
  ["critical", "bg-sev-critical-bg text-sev-critical-text"],
  ["high", "bg-sev-high-bg text-sev-high-text"],
  ["medium", "bg-sev-medium-bg text-sev-medium-text"],
  ["low", "bg-sev-low-bg text-sev-low-text"],
] as const;

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

function Cell({ r, col }: { r: EntityRisk; col: Column }) {
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
export function RiskTable({ label, kind, rows, onPick }: RiskTableProps) {
  const top = Math.max(1, ...rows.map((r) => r.score));
  const cols = COLUMNS[kind];
  const NUM = "px-3 py-2 text-right font-mono tabular-nums align-top";
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} className="w-full min-w-[760px] text-sm">
        <thead>
          <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
            <th className="px-3 py-2 font-semibold">{label}</th>
            <th className="w-40 px-3 py-2 text-right font-semibold">Score</th>
            <th className="px-3 py-2 font-semibold">Rule matches</th>
            {cols.map((c) => (
              <th key={c} className="px-3 py-2 text-right font-semibold">
                {PART_LABEL[c]}
              </th>
            ))}
            <th className="px-3 py-2 text-right font-semibold">Events</th>
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
                <div className="flex items-center justify-end gap-2" title={scoreTitle(r)}>
                  <span className="h-1.5 w-24 rounded bg-surface-head" aria-hidden="true">
                    <span
                      className="block h-1.5 rounded bg-danger"
                      style={{ width: `${r.score ? Math.max(4, (r.score / top) * 100) : 0}%` }}
                    />
                  </span>
                  <span className="w-8 text-right font-mono tabular-nums">{r.score}</span>
                </div>
              </td>
              <td className="px-3 py-2 align-top" title={r.rules.join(", ") || undefined}>
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
                  {!r.critical && !r.high && !r.medium && !r.low && !r.flagged_runs ? (
                    <span className="font-mono text-text-muted">0</span>
                  ) : null}
                </div>
              </td>
              {cols.map((c) => (
                <td key={c} className={NUM}>
                  <Cell r={r} col={c} />
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
