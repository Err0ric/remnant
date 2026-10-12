/**
 * A one-shot handoff into Search (for example "Open in Search" from rule matches). Kept in
 * memory for this tab and taken once when the Search page opens; the SQL still runs
 * through the server's guard like anything typed in the editor.
 */
export interface SearchSeed {
  /** SQL to open on the SQL tab over all time. */
  sql?: string;
  /** Sources to filter to; the server still limits them to the caller's own. */
  sources?: string[];
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
