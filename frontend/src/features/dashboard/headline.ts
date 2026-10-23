import type { Schedule, ScheduleRunSummary } from "@/lib/api";

/** The panel's number for a run (ADR-0034): the stored headline, or the row count for runs
 * made before headlines existed. null: the headline column was not in the result. */
export function headlineValue(s: Schedule, run: ScheduleRunSummary): string | null {
  if (run.headline !== undefined && run.headline !== null) return run.headline;
  if ((s.headline_kind ?? "rows") === "rows") return String(run.row_count ?? 0);
  return null;
}

/** What the number counts: the owner's label, or a plain default. */
export function headlineLabel(s: Schedule): string {
  if (s.headline_label) return s.headline_label;
  const col = s.headline_column ?? "";
  switch (s.headline_kind ?? "rows") {
    case "sum":
      return `total ${col}`;
    case "distinct":
      return `distinct ${col}`;
    case "first":
      return col;
    default:
      return s.kind === "rule" ? "matches" : "rows";
  }
}

/** Numbers for the trend line, oldest first: each run's headline when numeric, else its
 * row count; null where a run failed or is restricted. */
export function trend(s: Schedule): (number | null)[] {
  return [...s.recent].reverse().map((r) => {
    if (r.status !== "ok" || r.restricted) return null;
    const v = Number(headlineValue(s, r));
    return Number.isFinite(v) ? v : r.row_count;
  });
}

/** "1,234" for numbers, the text as it is otherwise. */
export function formatHeadline(v: string): string {
  const n = Number(v);
  return v.trim() !== "" && Number.isFinite(n) ? n.toLocaleString() : v;
}

/** What one row of a result is, from its first column: "3 addresses", not "3 rows". */
export function rowNoun(s: Schedule, columns: string[]): string {
  if (s.kind === "rule") return "matches";
  const c = (columns[0] ?? "").toLowerCase();
  if (/(^|_)(ip|addr|address|src|dst)(_|$)|src_endpoint|dst_endpoint/.test(c)) return "addresses";
  if (/user|person|actor|account|who/.test(c)) return "people";
  if (/host|device|machine|computer/.test(c)) return "devices";
  if (/source/.test(c)) return "sources";
  if (/service|app/.test(c)) return "services";
  if (/rule/.test(c)) return "rules";
  if (/domain|site|url/.test(c)) return "domains";
  return "results";
}

/** The panel's label: the owner's, else what the number counts in plain words. */
export function panelLabel(s: Schedule, columns: string[]): string {
  if (s.headline_label) return s.headline_label;
  return (s.headline_kind ?? "rows") === "rows" ? rowNoun(s, columns) : headlineLabel(s);
}

/** The flag in plain words: "3 addresses over threshold (0)". */
export function flagText(s: Schedule, run: ScheduleRunSummary, columns: string[]): string | null {
  if (!run.flagged) return null;
  const n = run.row_count ?? 0;
  const noun = rowNoun(s, columns);
  const v = s.threshold_value ?? 0;
  if (s.threshold_kind === "above") return `${n.toLocaleString()} ${noun} over threshold (${v})`;
  if (s.threshold_kind === "below") return `${n.toLocaleString()} ${noun}, under threshold (${v})`;
  return run.flag_reason;
}

/** The trend line only says something once there are a few runs that counted. */
export const MIN_TREND_RUNS = 3;

export function hasTrend(s: Schedule): boolean {
  return s.recent.filter((r) => r.status === "ok" && !r.restricted).length >= MIN_TREND_RUNS;
}

/** A range in words: "Last 24 hours", "Last 7 days", "Last 12 months". */
export function rangeWords(minutes: number | null): string | null {
  if (!minutes) return null;
  const days = minutes / 1440;
  if (days >= 365 && days <= 366) return "Last 12 months";
  if (Number.isInteger(days) && days >= 2) return `Last ${days} days`;
  const hours = minutes / 60;
  if (Number.isInteger(hours)) return hours === 1 ? "Last hour" : `Last ${hours} hours`;
  return `Last ${minutes} minutes`;
}
