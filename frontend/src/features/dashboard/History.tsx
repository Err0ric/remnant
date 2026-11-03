const day = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });

/** The window length a "the previous 7 days" or "the previous 24 hours" phrase names. */
function daysIn(before: string): number {
  const m = /(\d+)\s+(day|hour)/.exec(before);
  if (!m) return 7;
  return m[2] === "hour" ? Number(m[1]) / 24 : Number(m[1]);
}

/** The section header's comparison line: the one place a section says whether its numbers
 * are compared, so cards no longer repeat "Not enough history" under every number (owner,
 * 2026-11-02). Comparisons start once the window before is covered: two windows after the
 * data starts. */
export function compareLine(compared: boolean, since: string | null, before: string): string {
  if (compared) return `Changes against ${before}`;
  if (!since) return "No comparison yet";
  const start = new Date(new Date(since).getTime() + 2 * daysIn(before) * 86_400_000);
  return `Comparisons start ${day(start.toISOString())}`;
}
