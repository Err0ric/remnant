import type { PageTime } from "@/lib/timeChoice";
import { windowOf } from "@/lib/timeWindow";

/** The most an Agents read covers: the server's bound for its windows. */
const MOST_MS = 90 * 86_400_000;

/** The one window every number on Agents covers (PR 639 review): the time chosen, exactly,
 * for the header, the strip, Needs attention, and the tables alike. */
export interface AgentWindow {
  /** For a query key: changes when the choice does, not as the clock moves. */
  key: readonly string[];
  /** What the person chose, as the API takes it: an open end stays open and a missing
   * start stays missing; the server applies the 90-day cap on its own clock. */
  bounds: () => { start?: string; end?: string };
  /** Days before the end when there is no start: the server's cap. */
  days: number;
  /** The server will read less than the choice (its last 90 days): a Custom range with no
   * start or longer than 90 days. Presets never are. */
  clamps: boolean;
  /** "Last 7 days", "Last hour", or "Nov 1, 9:00 AM to Nov 3, 5:00 PM" for Custom. */
  words: string;
  /** "previous 7 days": what the changes are against. */
  before: string;
}

const PRESET: Record<string, string> = {
  "1h": "Last hour",
  "24h": "Last 24 hours",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
};

const when = (at: Date) =>
  at.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

/** The page's time as Agents reads it. Custom with no start, or longer than 90 days, reads
 * the 90 days to its end (the server's cap), and its words say so. */
export function agentWindow(time: PageTime): AgentWindow {
  const { choice } = time;
  const w = windowOf(choice);
  const end = w.to ?? new Date();
  const cut = !w.from || end.getTime() - w.from.getTime() > MOST_MS;
  const to = w.to ? when(w.to) : "now";
  return {
    key: time.key,
    bounds: () => {
      const v = windowOf(choice);
      return { start: v.from?.toISOString(), end: v.to?.toISOString() };
    },
    days: 90,
    clamps: cut,
    words:
      PRESET[choice.preset] ?? (cut ? `The 90 days to ${to}` : `${when(w.from as Date)} to ${to}`),
    before: time.before,
  };
}
