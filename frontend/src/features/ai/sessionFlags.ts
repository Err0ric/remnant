import type { AgentAccount, AgentSession } from "@/lib/api";

/** A session row's flags (owner, 2026-11-03; D188). */
export type SessionFlag = "failed" | "personal" | "new_mcp";

export const FLAG_LABEL: Record<SessionFlag, string> = {
  failed: "Blocked or failed call",
  personal: "Personal account",
  new_mcp: "New MCP server",
};

/** What a session's flags are read from: a list row, or the session's summary. */
export type FlagInputs = Pick<AgentSession, "failed" | "unanswered" | "state" | "new_mcp"> &
  Partial<Pick<AgentSession, "stopped" | "masked" | "account" | "person">>;

/** Tool calls that failed, plus those with no result once the session is not open. */
export function failedOrBlocked(s: FlagInputs): number {
  const closed = (s.state ?? (s.stopped ? "ended" : "open")) !== "open";
  return (s.failed ?? 0) + (closed ? (s.unanswered ?? 0) : 0);
}

export function sessionFlags(
  s: FlagInputs,
  account: (email: string | null) => AgentAccount | undefined,
): SessionFlag[] {
  const out: SessionFlag[] = [];
  // A call with no result in a session still running may simply not have returned yet.
  if (failedOrBlocked(s) > 0) out.push("failed");
  // Masked (D242): the account is a machine, so it is not looked up.
  if (!s.masked && account(s.account ?? s.person ?? null)?.tier === "personal")
    out.push("personal");
  if ((s.new_mcp ?? []).length > 0) out.push("new_mcp");
  return out;
}

/** "45 min", "2 h 5 min", "under a minute". */
export function duration(startIso: string, endIso: string): string {
  const m = Math.round((new Date(endIso).getTime() - new Date(startIso).getTime()) / 60000);
  if (m < 1) return "under a minute";
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
}
