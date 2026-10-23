import type { SourceGap } from "@/lib/api";

/** "2:00 AM" in the viewer's zone (or `timeZone`, for tests). */
export function localTime(iso: string, timeZone?: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  });
}

/** "2 AM": an axis label. */
export function localHour(iso: string, timeZone?: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", timeZone });
}

/** "PDT", "UTC+2": the zone's short name, shown wherever local times are. */
export function zoneName(timeZone?: string): string {
  const part = new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "short" })
    .formatToParts(new Date())
    .find((p) => p.type === "timeZoneName");
  return part?.value ?? "local time";
}

function day(iso: string, timeZone?: string): string {
  return new Date(iso).toLocaleDateString("en-CA", { timeZone });
}

/** The gap in words, in local time (F55): "No events 2:00 to 7:00 AM (5 h). Other sources
 * kept flowing." Days are named only when the gap started before today. */
export function gapText(gap: SourceGap, now: string, timeZone?: string): string {
  const from = localTime(gap.start, timeZone);
  const earlier = day(gap.start, timeZone) !== day(now, timeZone) ? "yesterday " : "";
  const others = gap.others_flowing ? " Other sources kept flowing." : "";
  if (gap.ongoing || !gap.end)
    return `No events since ${earlier}${from} (${gap.hours} h so far).${others}`;
  const to = localTime(gap.end, timeZone);
  const [fromClock, fromHalf] = from.split(" ");
  const [, toHalf] = to.split(" ");
  const start = fromHalf === toHalf && !earlier ? fromClock : from;
  return `No events ${earlier}${start} to ${to} (${gap.hours} h).${others}`;
}

/** The Events tile's comparison (F60): only with 7 full days, only over sources that have
 * them, and saying when newer sources are left out. */
export function eventsChange(o: {
  history_days: number;
  events_compared_24h: number;
  events_usual_24h: number | null;
  new_sources: string[];
}): string {
  if (o.history_days < 7 || o.events_usual_24h === null)
    return `Not enough history yet (${o.history_days} of 7 days)`;
  const base = changeText(o.events_compared_24h, o.events_usual_24h) ?? "No events on earlier days";
  const n = o.new_sources.length;
  return n ? `${base}, leaving out ${n} new ${n === 1 ? "source" : "sources"}` : base;
}

/** "+4% vs a usual day", "same as usual", or nothing without history. */
export function changeText(now: number, usual: number | null): string | null {
  if (usual === null || usual <= 0) return null;
  const pct = Math.round(((now - usual) / usual) * 100);
  if (pct === 0) return "same as a usual day";
  return `${pct > 0 ? "+" : ""}${pct}% vs a usual day`;
}

/** "4 s", "12 min", "3 h": how long ago the newest event arrived. */
export function lag(last: string | null, now: string): string | null {
  if (!last) return null;
  const s = Math.max(0, (Date.parse(now) - Date.parse(last)) / 1000);
  if (Number.isNaN(s)) return null;
  if (s < 90) return `${Math.round(s)} s`;
  if (s < 90 * 60) return `${Math.round(s / 60)} min`;
  if (s < 48 * 3600) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / 86400)} d`;
}
