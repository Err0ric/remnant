export type EntityKind = "user" | "ip" | "host";

const IPV4 = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;
const IPV6 = /^[0-9a-f]{0,4}(:[0-9a-f]{0,4}){2,7}(%\w+)?$/i;
const KEY = "investigate.kind";

export const PLACEHOLDER: Record<EntityKind, string> = {
  ip: "203.0.113.9",
  user: "alice@example.com",
  host: "ws-0042",
};

/** What the typed value looks like (F56): an IPv4 or IPv6 address is an IP address;
 * `name@domain` or `DOMAIN\user` is a user; anything else is a host. */
export function kindOf(text: string): EntityKind | null {
  const v = text.trim();
  if (!v) return null;
  if (IPV4.test(v) || (v.includes(":") && IPV6.test(v))) return "ip";
  if (v.includes("@") || v.includes("\\")) return "user";
  return "host";
}

/** The type used last in this browser; IP address the first time. */
export function rememberedKind(): EntityKind {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "user" || v === "host" || v === "ip" ? v : "ip";
  } catch {
    return "ip";
  }
}

export function rememberKind(kind: EntityKind) {
  try {
    window.localStorage.setItem(KEY, kind);
  } catch {
    // Storage blocked: the page still works, it just starts from IP address next time.
  }
}
