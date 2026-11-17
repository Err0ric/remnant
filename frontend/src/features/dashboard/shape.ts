import type { Overview, PageWindow, Source } from "@/lib/api";
import { quietFrom } from "@/features/health/flow";

/** What the Dashboard draws, decided before any number arrives (fix list 2026-11-16 item 27):
 * from the viewer's own sources (GET /api/sources lists only those), by the server's rule
 * for each section. The strip's tiles and the section boxes take their place from the first
 * paint, so nothing moves when the numbers come; a part whose data turns out empty keeps its
 * box and says so. */
export interface DashboardShape {
  /** A Microsoft 365 source: the two sign-in tiles and Identity. */
  m365: boolean;
  /** A source that is not Microsoft 365: Attacks and access. */
  other: boolean;
  /** Any source: AI services in use, Sources healthy, AI Watch, and Detections. */
  any: boolean;
}

export const isM365 = (s: Pick<Source, "kind" | "template_id">): boolean =>
  s.kind === "m365" || (s.template_id ?? "").startsWith("m365_");

export function shapeOf(sources: Pick<Source, "kind" | "template_id">[]): DashboardShape {
  return {
    m365: sources.some(isM365),
    other: sources.some((s) => !isM365(s)),
    any: sources.length > 0,
  };
}

/** The strip's tiles, in order, for a shape: Open alerts always. */
export function kpiKeys(shape: DashboardShape): string[] {
  return [
    "alerts",
    ...(shape.m365 ? ["failed", "outside"] : []),
    ...(shape.any ? ["ai", "sources"] : []),
  ];
}

/** Where the window starts, as the server counts it (`bounds` in app/search/dashboard.py):
 * for 24 hours the hour 23 hours before this one, else local midnight N - 1 days ago; and
 * where the window before it starts. */
export function windowStarts(win: PageWindow, now: Date): { start: Date; before: Date } {
  if (win === "24h") {
    const top = new Date(now);
    top.setUTCMinutes(0, 0, 0);
    const start = new Date(top.getTime() - 23 * 3_600_000);
    return { start, before: new Date(start.getTime() - 24 * 3_600_000) };
  }
  const days = win === "7d" ? 7 : 30;
  const day = (n: number) => {
    const d = new Date(now);
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - n);
    return d;
  };
  return { start: day(days - 1), before: day(2 * days - 1) };
}

/** A metadata time ("2026-11-16 10:00:00", UTC) or an ISO time, as a Date. */
const when = (t: string): Date =>
  new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(t) ? t : `${t.replace(" ", "T")}Z`);

/** What the page knows is empty before the sections answer, from the quick reads: no rule
 * enabled and no rule match since the window before (Detections: its empty state at its
 * own height; exact, so its answer is not asked for), and every source Attacks and access
 * counts, but the server's own, with its newest event before the window starts (its
 * compact empty card; its answer still loads, and shows if it has something after all). */
export function knownEmpty(
  win: PageWindow,
  sources: Pick<Source, "source_id" | "kind" | "template_id" | "built_in">[] | undefined,
  overview: Overview | undefined,
  now = new Date(),
): { detections: boolean; attacks: boolean } {
  const { start, before } = windowStarts(win, now);
  const last = overview?.rules_last_match ?? null;
  const detections = overview?.rules_enabled === 0 && (last === null || when(last) < before);
  const health = new Map((overview?.sources ?? []).map((h) => [h.source_id, h]));
  // The server's own events (built in) arrive on every request, so they never look quiet;
  // a failed sign-in to this server from outside is rare, and the section still loads.
  const counted = (sources ?? []).filter((s) => !isM365(s) && !s.built_in);
  const attacks =
    counted.length > 0 &&
    counted.every((s) => {
      const h = health.get(s.source_id);
      const newest = h ? quietFrom(h) : undefined;
      return newest === null || (newest !== undefined && when(newest) < start);
    });
  return { detections, attacks };
}
