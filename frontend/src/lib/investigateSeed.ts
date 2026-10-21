/** A one-shot handoff into Investigations ("Investigate" on a field in Search), taken
 * once when the page opens. */
export interface InvestigateSeed {
  kind: "user" | "ip" | "host";
  value: string;
}

let seed: InvestigateSeed | null = null;

export function seedInvestigate(value: InvestigateSeed): void {
  seed = value;
}

export function takeInvestigateSeed(): InvestigateSeed | null {
  const value = seed;
  seed = null;
  return value;
}

/** Columns whose values are entities the investigator can open. */
export const ENTITY_COLUMNS: Record<string, InvestigateSeed["kind"]> = {
  actor_user_name: "user",
  src_endpoint_ip: "ip",
  dst_endpoint_ip: "ip",
  device_hostname: "host",
  src_endpoint_hostname: "host",
};
