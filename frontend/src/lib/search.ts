import type { Cell } from "./api";

export const TIME_RANGES = [
  { id: "15m", label: "Last 15 minutes", ms: 15 * 60_000 },
  { id: "1h", label: "Last hour", ms: 3_600_000 },
  { id: "24h", label: "Last 24 hours", ms: 86_400_000 },
  { id: "7d", label: "Last 7 days", ms: 7 * 86_400_000 },
  { id: "30d", label: "Last 30 days", ms: 30 * 86_400_000 },
  { id: "all", label: "All time", ms: null },
] as const;

export type TimeRangeId = (typeof TIME_RANGES)[number]["id"];

export function rangeStart(id: TimeRangeId, now: Date = new Date()): string | undefined {
  const range = TIME_RANGES.find((r) => r.id === id);
  return range?.ms ? new Date(now.getTime() - range.ms).toISOString() : undefined;
}

export const DEFAULT_SQL = [
  "SELECT time, severity_id, source_id, device_hostname, actor_process_name, message, event_id",
  "FROM events",
  "ORDER BY coalesce(time, time_observed) DESC",
].join("\n");

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** SQL to load one full event. The id is validated so only a UUID reaches the SQL text. */
export function eventSql(eventId: string): string | null {
  return UUID.test(eventId) ? `SELECT * FROM events WHERE event_id = '${eventId}' LIMIT 1` : null;
}

/** Raw lines for a page of results, by event id, through the normal guarded query path. */
export function rawSql(eventIds: string[]): string | null {
  const ids = eventIds.filter((id) => UUID.test(id));
  if (ids.length === 0) return null;
  return `SELECT event_id, raw FROM events WHERE event_id IN (${ids.map((id) => `'${id}'`).join(", ")})`;
}

export function formatCell(value: Cell): string {
  if (value === null || value === undefined || value === "") return "·";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const UTC_STAMP = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.\d+)?(?:Z|\+00:00)$/;

/** A cell as the results table shows it: UTC times to the second, without the T. */
export function displayCell(value: Cell): string {
  const text = formatCell(value);
  const m = typeof value === "string" ? UTC_STAMP.exec(value) : null;
  return m ? `${m[1]} ${m[2]}` : text;
}

// Plain headers for the columns people see most; the column name stays in the tooltip
// and in SQL. Anything else shows its column name.
const LABELS: Record<string, string> = {
  time: "Time",
  time_observed: "Received",
  severity_id: "Severity",
  source_id: "Source",
  device_hostname: "Host",
  device_ip: "Host IP",
  actor_process_name: "Process",
  actor_process_pid: "PID",
  actor_user_name: "User",
  src_endpoint_ip: "Source IP",
  dst_endpoint_hostname: "Destination host",
  src_endpoint_port: "Source port",
  dst_endpoint_ip: "Destination IP",
  dst_endpoint_port: "Destination port",
  message: "Message",
  event_id: "Event ID",
  raw: "Raw",
  parse_status: "Parse status",
};

export function columnLabel(name: string): string {
  return LABELS[name] ?? name;
}

export const SEVERITY: Record<number, { label: string; tone: string }> = {
  0: { label: "Unknown", tone: "info" },
  1: { label: "Info", tone: "info" },
  2: { label: "Low", tone: "low" },
  3: { label: "Medium", tone: "medium" },
  4: { label: "High", tone: "high" },
  5: { label: "Critical", tone: "critical" },
  6: { label: "Critical", tone: "critical" },
};

/**
 * Shared grid template for the results table. Every row uses the same column widths,
 * sized from the header and the values on the current page (in ch, since values are
 * monospace), capped so one long value cannot push the rest off screen.
 */
export function columnTemplate(
  columns: string[],
  rows: Cell[][],
  indexes: number[],
  maxCh = 48,
): string {
  const widths = indexes.map((i, pos) => {
    const name = columns[i] ?? "";
    if (name === "severity_id") return 12;
    let longest = columnLabel(name).length;
    for (const row of rows) {
      const text = displayCell(row[i] ?? null);
      if (text.length > longest) longest = text.length;
      if (longest >= maxCh) break;
    }
    const ch = Math.min(longest, maxCh) + 3; // room for cell padding
    return pos === indexes.length - 1 ? -ch : ch;
  });
  const parts = widths.map((w) => (w < 0 ? `minmax(${-w}ch, 1fr)` : `${w}ch`));
  return ["32px", ...parts].join(" ");
}

/** {{name}} placeholders in saved-search SQL (start and end come from the time range). */
export function sqlPlaceholders(sql: string): string[] {
  const names = new Set<string>();
  for (const m of sql.matchAll(/\{\{\s*([a-z_][a-z0-9_]{0,31})\s*\}\}/g)) {
    const name = m[1];
    if (name && name !== "start" && name !== "end") names.add(name);
  }
  return [...names];
}

/** A saved-search id from its name: lowercase, digits, _ and -, at most 64 characters. */
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 64);
}

export type SortDir = "asc" | "desc";

/** Rows ordered by one column, without changing the input. Numbers compare as numbers,
 * everything else as text (case-insensitive, natural for digits); empty values always
 * sort last. Only the rows already returned are sorted, never the whole result set. */
export function sortRows<T extends Cell[]>(rows: T[], index: number, dir: SortDir): T[] {
  const sign = dir === "asc" ? 1 : -1;
  const empty = (v: Cell | undefined) => v === null || v === undefined || v === "";
  return [...rows].sort((a, b) => {
    const x = a[index];
    const y = b[index];
    if (empty(x) || empty(y)) return empty(x) === empty(y) ? 0 : empty(x) ? 1 : -1;
    if (typeof x === "number" && typeof y === "number") return (x - y) * sign;
    return (
      formatCell(x ?? null).localeCompare(formatCell(y ?? null), undefined, {
        numeric: true,
        sensitivity: "base",
      }) * sign
    );
  });
}
