export interface InvestigateSeed {
  kind: "user" | "ip" | "host";
  value: string;
}

/** Columns whose values are entities the investigator can open. */
export const ENTITY_COLUMNS: Record<string, InvestigateSeed["kind"]> = {
  actor_user_name: "user",
  src_endpoint_ip: "ip",
  dst_endpoint_ip: "ip",
  device_hostname: "host",
  src_endpoint_hostname: "host",
};
