const day = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
const hour = (d: Date) => d.toLocaleTimeString("en-US", { hour: "numeric" });

/** The section header's comparison line: the one place a section says whether its numbers
 * are compared, so cards no longer repeat "Not enough history" under every number (owner,
 * 2026-11-02). When comparisons start is the server's one rule (`comparisons_start`): the
 * first moment the window before is covered by the section's sources. The page does no date
 * math of its own (fix list item 8). */
export function compareLine(
  compared: boolean,
  starts: string | null | undefined,
  before: string,
): string {
  if (compared) return `Changes against ${before}`;
  if (!starts) return "No comparison yet";
  const at = new Date(starts);
  // A 24-hour window can start comparing at any hour; days start at midnight.
  const when = /hour/.test(before) ? `${day(at)}, ${hour(at)}` : day(at);
  return `Comparisons start ${when}, when the window before has data`;
}
