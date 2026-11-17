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

/** "Nov 8, 7:19 AM" in the viewer's zone, as `When` shows it, for text that cannot hold
 * an element (a reason line, a joined detail). */
export function localStamp(iso: string, timeZone?: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const text = d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  });
  return text + zoneIfRepeated(d, timeZone);
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

/** How far the zone's wall clock is ahead of UTC at that moment, in ms. */
function offsetAt(ms: number, timeZone?: string): number {
  const p: Record<string, number> = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone,
      hourCycle: "h23",
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "numeric",
      second: "numeric",
    })
      .formatToParts(new Date(ms))
      .map((x) => [x.type, Number(x.value)]),
  );
  const n = (k: string) => p[k] ?? 0;
  return Date.UTC(n("year"), n("month") - 1, n("day"), n("hour"), n("minute"), n("second")) - ms;
}

/** The UTC instant of local midnight on "YYYY-MM-DD". */
function localMidnight(day: string, timeZone?: string): number {
  const wall = Date.parse(`${day}T00:00:00Z`);
  const guess = wall - offsetAt(wall, timeZone);
  return wall - offsetAt(guess, timeZone);
}

/** A day the charts count in the viewer's zone, as UTC bounds for Logs: a bar for Nov 4
 * opens Nov 4 local, not Nov 4 UTC (owner, 2026-11-08). */
export function localDayBounds(day: string, timeZone?: string): { start: string; end: string } {
  const next = new Date(Date.parse(`${day}T12:00:00Z`) + 86_400_000).toISOString().slice(0, 10);
  return {
    start: new Date(localMidnight(day, timeZone)).toISOString(),
    end: new Date(localMidnight(next, timeZone)).toISOString(),
  };
}

/** The one note under a page's local times (DESIGN.md section 3): "Times in PDT; hover for
 * UTC.", or "Times in UTC." when the viewer's zone is UTC, where the hover would add nothing. */
export function timesNote(zone: string): string {
  return zone === "UTC" || zone === "GMT" ? "Times in UTC." : `Times in ${zone}; hover for UTC.`;
}
