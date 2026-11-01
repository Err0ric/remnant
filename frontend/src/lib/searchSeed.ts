import type { TimeRangeId } from "@/lib/search";

/**
 * A one-shot handoff into Search (for example "Open in Search" from rule matches). Kept in
 * memory for this tab and taken once when the Search page opens; the SQL still runs
 * through the server's guard like anything typed in the editor.
 */
export interface SearchSeed {
  /** SQL to open on the SQL tab. */
  sql?: string;
  /** Sources to filter to; the server still limits them to the caller's own. */
  sources?: string[];
  /** Time range to open with (Investigations passes its own); all time otherwise. */
  range?: TimeRangeId;
  /** A page's own window (a drill-through): Search opens on exactly it, and the query
   * reads it through {{start}} and {{end}}, so another range or a saved copy still works. */
  window?: { from: string; to: string };
  /** A saved search to open for editing (Saved searches > Edit, F37). */
  savedId?: string;
  /** Where the query came from, shown above it ("From Dashboard > Identity > ..."). */
  origin?: string;
  /** Open the query library panel (command palette). */
  library?: boolean;
}

let seed: SearchSeed | null = null;
let version = 0;
const listeners = new Set<() => void>();

export function seedSearch(value: SearchSeed): void {
  seed = value;
  version += 1; // remounts an open Search page so it takes the seed
  listeners.forEach((l) => l());
}

export function subscribeSeed(callback: () => void): () => void {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

export function seedVersion(): number {
  return version;
}

/** Asks an open Search page to run what it shows (command palette "Run"). */
export const RUN_SEARCH_EVENT = "app:run-search";

export function takeSearchSeed(): SearchSeed | null {
  const value = seed;
  seed = null;
  return value;
}

const EVENT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** SQL listing these events; ids that are not UUIDs are dropped, never quoted in. */
export function eventsSql(eventIds: string[]): string {
  const ids = eventIds.filter((id) => EVENT_ID.test(id)).slice(0, 500);
  const list = ids.length ? ids.map((id) => `'${id}'`).join(", ") : "''";
  return [
    "SELECT time, severity_id, source_id, device_hostname, message, event_id",
    "FROM events",
    `WHERE event_id IN (${list})`,
    "ORDER BY coalesce(time, time_observed)",
  ].join("\n");
}

const HOUR_START = /^\d{4}-\d{2}-\d{2}T\d{2}:00:00(\+00:00|Z)$/;

/** SQL listing one source's events in one hour (Overview heatmap). The source id is
 * quoted as a string literal and the hour must be a plain UTC hour start. */
export function hourSql(sourceId: string, hourStart: string): string | null {
  if (!HOUR_START.test(hourStart)) return null;
  const start = new Date(hourStart);
  const end = new Date(start.getTime() + 3_600_000).toISOString().replace(".000Z", "+00:00");
  const ts = "coalesce(time, time_observed)";
  return [
    "SELECT time, severity_id, source_id, device_hostname, message, event_id",
    "FROM events",
    `WHERE source_id = '${sourceId.replace(/'/g, "''")}'`,
    `  AND ${ts} >= TIMESTAMPTZ '${hourStart}'`,
    `  AND ${ts} < TIMESTAMPTZ '${end}'`,
    `ORDER BY ${ts}`,
  ].join("\n");
}
