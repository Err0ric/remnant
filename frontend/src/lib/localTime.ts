/** Times in the viewer's zone around a clock change (owner, 2026-11-01): when the same
 * local hour happens twice (fall back), a time in it carries its zone ("1:15 AM PDT",
 * "1:15 AM PST") so two rows that read the same are told apart. */

const HOUR = 3_600_000;

function hourKey(d: Date, timeZone?: string): string {
  return d.toLocaleString("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  });
}

/** True when this local hour also happens an hour earlier or later. */
export function repeatsLocalHour(d: Date, timeZone?: string): boolean {
  const k = hourKey(d, timeZone);
  return (
    hourKey(new Date(d.getTime() - HOUR), timeZone) === k ||
    hourKey(new Date(d.getTime() + HOUR), timeZone) === k
  );
}

/** "PDT", "GMT+5:30": the zone's short name at that moment. */
export function zoneName(d: Date, timeZone?: string): string {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "short" });
  return parts.formatToParts(d).find((p) => p.type === "timeZoneName")?.value ?? "";
}

/** " PDT" when the hour repeats, otherwise "". */
export function zoneIfRepeated(d: Date, timeZone?: string): string {
  return repeatsLocalHour(d, timeZone) ? ` ${zoneName(d, timeZone)}` : "";
}

/** The viewer's date as "YYYY-MM-DD", for grouping by day. */
export function localDate(d: Date, timeZone?: string): string {
  return d.toLocaleDateString("en-CA", { timeZone });
}

/** "01:15", or "01:15 PDT" in a repeated hour. */
export function localClock(d: Date, timeZone?: string): string {
  const hm = d.toLocaleTimeString("en-GB", {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  return hm + zoneIfRepeated(d, timeZone);
}
