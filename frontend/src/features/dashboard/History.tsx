const day = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

/** Shown on a card instead of the change pill while the period before is only partly
 * covered by the sources behind it (owner 2026-10-30), like the Events tile (F60). */
export function NoHistory({ since, before }: { since: string | null; before: string }) {
  return (
    <span
      className="text-sm text-text-muted"
      title={
        since
          ? `Data starts ${day(since)}, so ${before} are only partly covered.`
          : `${before.replace(/^t/, "T")} are only partly covered.`
      }
    >
      Not enough history for comparison
    </span>
  );
}

/** The section header's comparison line. */
export function compareLine(compared: boolean, since: string | null, before: string): string {
  if (compared) return `Changes against ${before}`;
  return since ? `No comparison yet: data starts ${day(since)}` : "No comparison yet";
}
