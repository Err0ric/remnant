import type { AddressSpan } from "@/lib/api";

const KIND: Record<AddressSpan["kind"], string> = {
  vpn: "GlobalProtect login",
  userid: "User-ID",
  logon: "Logon",
  dhcp: "DHCP lease",
  signin: "Company sign-in",
};

function clock(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** One match in words, with what it gave and whether its end was assumed (D107 C1):
 * "GlobalProtect login Oct 9, 9:02 AM: alice on LAPTOP-A (no logout seen, assumed until
 * Oct 9, 9:02 PM)". */
export function matchText(s: AddressSpan): string {
  const what =
    s.kind === "dhcp"
      ? `${s.machine ?? "a machine"}${s.mac ? ` (MAC ${s.mac})` : ""}`
      : s.kind === "signin"
        ? `${s.person} on ${s.machine}`
        : [s.person, s.machine].filter(Boolean).join(" on ");
  const end =
    s.capped && s.end
      ? ` (no ${s.kind === "vpn" || s.kind === "userid" ? "logout" : "end"} seen, assumed until ${clock(s.end)})`
      : "";
  return `${KIND[s.kind]} ${clock(s.start)}: ${what}${end}`;
}
