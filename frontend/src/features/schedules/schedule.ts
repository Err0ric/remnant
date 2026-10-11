import type { Cell, ScheduleRunSummary } from "@/lib/api";

const PRESET_LABELS: Record<string, string> = {
  "0 * * * *": "Hourly",
  "0 7 * * *": "Daily at 07:00",
  "0 7 * * 1-5": "Weekdays at 07:00",
};

export const PRESETS = [
  { value: "hourly", label: "Hourly" },
  { value: "daily", label: "Daily at 07:00" },
  { value: "weekdays", label: "Weekdays at 07:00" },
] as const;

export function cronLabel(cron: string): string {
  return PRESET_LABELS[cron] ?? `Cron ${cron}`;
}

export function lookbackLabel(minutes: number | null): string {
  if (!minutes) return "Since the last run";
  if (minutes % 1440 === 0) return `Last ${minutes / 1440} d`;
  if (minutes % 60 === 0) return `Last ${minutes / 60} h`;
  return `Last ${minutes} min`;
}

/** Counts for a sparkline, oldest first; restricted, paused, or failed runs are gaps. */
export function counts(recent: ScheduleRunSummary[]): (number | null)[] {
  return [...recent]
    .reverse()
    .map((r) => (r.status === "ok" && !r.restricted ? r.row_count : null));
}

function literal(value: Cell): string | null {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  if (typeof value === "string") return `'${value.replace(/'/g, "''")}'`;
  return null;
}

/**
 * The SQL of a scheduled saved search with its placeholders filled in as literals, so it can
 * be opened in Search for the same range. Returns null when a placeholder has no value. The
 * result runs as the viewer, through the server's guard, like anything typed in the editor.
 */
export function fillSql(
  sql: string,
  values: Record<string, Cell>,
  start: string,
  end: string,
): string | null {
  const all: Record<string, Cell> = { ...values, start, end };
  let missing = false;
  const out = sql.replace(/\{\{\s*([a-z_][a-z0-9_]{0,31})\s*\}\}/g, (_m, name: string) => {
    const v = all[name];
    if (name === "start" || name === "end") {
      return `TIMESTAMPTZ ${literal(String(v)) ?? "NULL"}`;
    }
    const lit = v === undefined ? null : literal(v);
    if (lit === null) missing = true;
    return lit ?? "NULL";
  });
  return missing ? null : out;
}
