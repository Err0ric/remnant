import type { Overview, SourceGap, SourceSummary } from "@/lib/api";

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

export interface OpenGap {
  source_id: string;
  /** The open source gap alert, or null when only the quiet watch says so. */
  item_id: string | null;
  /** "4 d": how long since the source last sent, or null when it never did. */
  quiet: string | null;
}

/** How many sources have something wrong, for the rail's Health dot: every condition but
 * healthy and paused (a source someone paused on purpose is not a problem to flag). The
 * same rule as the server's `needing_attention` behind `/api/health/count`. */
export function needingAttention(o: Overview | undefined): number {
  const rows = Array.isArray(o?.sources) ? o.sources : [];
  return rows.filter((r) => r.condition !== "healthy" && r.condition !== "paused").length;
}

/** Sources with an open gap (review item 3): an open source gap alert, or a quiet watch
 * that is firing. The same state the source gap alerts use, so the Dashboard footer,
 * Health, and Alerts agree. Longest quiet first. */
export function openGaps(o: Overview | undefined): OpenGap[] {
  const rows = Array.isArray(o?.sources) ? o.sources : [];
  return (
    rows
      // server_events is quiet whenever nobody uses the server: expected (handoff items 4, 9).
      .filter((s) => (s.gap_alert || s.quiet_since) && !s.quiet_expected)
      .sort((a, b) => (a.last_event_at ?? "").localeCompare(b.last_event_at ?? ""))
      .map((s) => ({
        source_id: s.source_id,
        item_id: s.gap_alert ?? null,
        quiet: o ? lag(s.last_event_at, o.generated_at) : null,
      }))
  );
}

/** "2 gaps: server_events quiet 4 d, lin_auth quiet 3 h". */
export function openGapsText(gaps: OpenGap[], max = 3): string {
  const named = gaps
    .slice(0, max)
    .map((g) => (g.quiet ? `${g.source_id} quiet ${g.quiet}` : `${g.source_id} never sent`));
  const more = gaps.length > max ? `, and ${gaps.length - max} more` : "";
  return `${gaps.length} ${gaps.length === 1 ? "gap" : "gaps"}: ${named.join(", ")}${more}`;
}

/** The gaps to draw and say for a source. A source marked "Quiet is normal" and inside its
 * days (`quiet_ok`, from the server) has none: gap hours are normal for it (D260). Health
 * and Sources both use this. */
export function shownGaps<G>(
  h: Pick<Overview["sources"][number], "quiet_ok"> | undefined,
  gaps: G[] | undefined,
): G[] {
  return h?.quiet_ok ? [] : (gaps ?? []);
}

/** "No events for 2 d (normal for this source)": an idle source, one marked "Quiet is
 * normal" that is silent inside its days (D260). Health and Sources say it alike. */
export function idleText(last: string | null, now: string): string {
  const q = lag(last, now);
  return `No events for ${q ?? "a while"} (normal for this source)`;
}

/** "quiet 4 d" or "never sent": a quiet source in the words both pages use. */
export function quietWord(last: string | null, now: string): string {
  const q = lag(last, now);
  return q ? `quiet ${q}` : "never sent";
}

/** The Sources summary in words, the same on Health and the Dashboard footer (handoff
 * item 4): "4 of 6 healthy", then "2 quiet: win_dc 2 d, vpn 6 h", the gaps, and the
 * longest wait when nothing is quiet. Counted once on the server (`source_summary`). */
export function sourcesSummaryText(
  s: SourceSummary,
  now: string,
  max = 3,
): { headline: string; details: string[] } {
  const named = s.quiet.slice(0, max).map((q) => {
    const w = quietWord(q.last_event_at, now);
    return `${q.source_id} ${w === "never sent" ? w : w.slice("quiet ".length)}`;
  });
  const more = s.quiet.length > max ? `, and ${s.quiet.length - max} more` : "";
  const wait = s.longest_wait ? lag(s.longest_wait.last_event_at, now) : null;
  return {
    headline: `${s.healthy} of ${s.total} healthy`,
    details: [
      s.quiet.length ? `${s.quiet.length} quiet: ${named.join(", ")}${more}` : null,
      s.gaps ? `${s.gaps} ${s.gaps === 1 ? "gap" : "gaps"} in 24 hours` : "no gaps in 24 hours",
      s.idle ? `${s.idle} idle (normal)` : null,
      !s.quiet.length && s.longest_wait && wait
        ? `longest wait ${wait} (${s.longest_wait.source_id})`
        : null,
    ].filter((d): d is string => Boolean(d)),
  };
}
