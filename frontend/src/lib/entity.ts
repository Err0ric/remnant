import { navigate } from "@/lib/route";

/** What a value can be opened as (product pass step 2): an address, a person, a machine,
 * or an AI service. */
export type EntityKind = "ip" | "user" | "host" | "service";

export interface Entity {
  kind: EntityKind;
  value: string;
}

/** Column names whose values are entities, wherever a table shows them: OCSF columns, the
 * names saved searches and panels use, and AI usage's own columns. */
const COLUMNS: Record<string, EntityKind> = {
  actor_user_name: "user",
  user: "user",
  user_name: "user",
  username: "user",
  person: "user",
  who: "user",
  src_endpoint_ip: "ip",
  dst_endpoint_ip: "ip",
  src_ip: "ip",
  dst_ip: "ip",
  ip: "ip",
  address: "ip",
  client_ip: "ip",
  device_hostname: "host",
  src_endpoint_hostname: "host",
  dst_endpoint_hostname: "host",
  hostname: "host",
  host: "host",
  device: "host",
  machine: "host",
  service_id: "service",
};

export function kindForColumn(column: string): EntityKind | null {
  return COLUMNS[column.toLowerCase()] ?? null;
}

/** Placeholders a table can hold that are not an entity. */
function blank(value: string): boolean {
  const v = value.trim();
  return !v || v === "-" || v === "·" || v === "null" || v === "[Unavailable]";
}

export function isEntityValue(value: unknown): value is string {
  return typeof value === "string" && !blank(value);
}

/** The Investigations address for an entity; kept in the fragment, so it never reaches a
 * server or proxy log, like Search (D90). */
export function entitySection(e: Entity): string {
  return `${e.kind}=${encodeURIComponent(e.value)}`;
}

export function entityHref(e: Entity): string {
  return `/investigations#${entitySection(e)}`;
}

export function parseEntity(section: string): Entity | null {
  const eq = section.indexOf("=");
  if (eq < 1) return null;
  const kind = section.slice(0, eq) as EntityKind;
  if (!["ip", "user", "host", "service"].includes(kind)) return null;
  try {
    const value = decodeURIComponent(section.slice(eq + 1));
    return isEntityValue(value) ? { kind, value } : null;
  } catch {
    return null;
  }
}

/** Opens the entity's page (a new history entry, so Back returns here). */
export function openEntity(e: Entity): void {
  navigate("investigate", entitySection(e));
}
