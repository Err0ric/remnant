import { When } from "@/components/When";
import type { SessionStep, SessionSummary } from "@/lib/api";
import { cn } from "@/lib/cn";
import { isFailed, segments, TYPES, type Segment } from "./barSegments";

interface SessionBarProps {
  steps: SessionStep[];
  summary: SessionSummary | undefined;
  /** With Flagged only, segments with no flagged step are dimmed and do nothing. */
  flagged: Set<string> | null;
  /** The steps with a row in the view below now (`shownSteps`), in order. */
  shown: SessionStep[];
  /** Opens a step in the view below (scrolls to it and focuses it). */
  onPick: (eventId: string) => void;
}

const n = (v: number | undefined) => (v ?? 0).toLocaleString();
const LABEL = Object.fromEntries(TYPES.map((t) => [t.type, t.label])) as Record<string, string>;

function hover(seg: Segment): string {
  const parts = Object.entries(seg.types).map(([t, c]) => `${LABEL[t]} ${n(c ?? 0)}`);
  return `${parts.join(", ")}${seg.failed ? ", failed" : ""}`;
}

/** The session from start to end (BACKLOG P1): one segment per step in order, each the
 * same width, colored by the server's step type, failed steps marked by a notch above in
 * --danger; a legend that names each type with its count for the whole session. The bar
 * is one image to assistive technology, summarized in its label; the steps themselves are
 * reached in the list below, so the bar adds no tab stops. */
/** The step a segment opens, from what the view shows now (never a step with no row):
 * with Flagged only, its first flagged step, and none when it holds none; otherwise its
 * first listed step, or the next listed one after it (a step Conversation does not list,
 * such as a second session start, opens the turn that follows). */
function targetOf(
  seg: Segment,
  flagged: Set<string> | null,
  listed: Set<string>,
  after: (id: string) => string | null,
): string | null {
  if (flagged !== null) return seg.ids.find((id) => flagged.has(id) && listed.has(id)) ?? null;
  return seg.ids.find((id) => listed.has(id)) ?? after(seg.ids[seg.ids.length - 1]!);
}

export function SessionBar({ steps, summary, flagged, shown, onPick }: SessionBarProps) {
  if (steps.length === 0) return null;
  const segs = segments(steps);
  const counts = summary?.types;
  const spoken = counts
    ? TYPES.map((t) => `${n(counts[t.type] ?? 0)} ${t.label.toLowerCase()}`).join(", ")
    : `${n(steps.length)} steps`;
  const failed = summary?.failed ?? steps.filter(isFailed).length;
  const listed = new Set(shown.map((s) => s.event_id));
  const order = new Map(steps.map((s, i) => [s.event_id, i]));
  const after = (id: string) =>
    shown.find((s) => (order.get(s.event_id) ?? -1) > (order.get(id) ?? Infinity))?.event_id ??
    null;
  // A 1px gap between segments only while there is room for it: a sliced session has up to
  // 280 segments, and gaps plus a minimum width would make the bar wider than a phone-width
  // pane. Both rows share the rule, so a failed notch always sits over its segment.
  const row = cn("flex min-w-0 overflow-hidden", segs.length <= 140 && "gap-px");
  return (
    <figure className="grid min-w-0 gap-1" aria-label="Session timeline bar">
      <div
        role="img"
        aria-label={`Session timeline: ${spoken}${failed ? `, ${n(failed)} failed` : ""}${summary?.steps_cut ? `; the bar shows the first ${n(steps.length)} steps` : ""}`}
        className="grid min-w-0 gap-px"
      >
        <div className={cn(row, "h-1")} aria-hidden="true">
          {segs.map((s) => (
            <span
              key={s.first}
              style={{ flexGrow: s.count, flexBasis: 0 }}
              className={cn("min-w-0", s.failed && "bg-danger")}
              data-failed={s.failed || undefined}
            />
          ))}
        </div>
        <div className={cn(row, "h-4")} data-bar="segments" aria-hidden="true">
          {segs.map((s) => {
            const target = targetOf(s, flagged, listed, after);
            const off = target === null;
            return (
              <span
                key={s.first}
                data-segment={s.type}
                data-opens={target ?? undefined}
                title={`${hover(s)}${off ? (flagged !== null ? " (not flagged)" : " (not listed in this view)") : ""}`}
                style={{ flexGrow: s.count, flexBasis: 0 }}
                onClick={off ? undefined : () => onPick(target)}
                className={cn(
                  "min-w-0",
                  TYPES.find((t) => t.type === s.type)?.fill,
                  off ? "opacity-25" : "cursor-pointer hover:opacity-80",
                )}
              />
            );
          })}
        </div>
      </div>
      <div className="flex justify-between text-xs text-text-muted">
        <When iso={steps[0]!.time} />
        <When iso={steps[steps.length - 1]!.time} />
      </div>
      <figcaption>
        <ul aria-label="Step types" className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {TYPES.map((t) => (
            <li key={t.type} className="flex items-center gap-1.5">
              <span aria-hidden="true" className={cn("inline-block h-3 w-3 rounded-sm", t.fill)} />
              <span className="text-text-secondary">{t.label}</span>
              <span className="tabular-nums">
                {counts
                  ? n(counts[t.type] ?? 0)
                  : n(steps.filter((s) => (s.type ?? "other") === t.type).length)}
              </span>
            </li>
          ))}
          {failed ? (
            <li className="flex items-center gap-1.5">
              <span aria-hidden="true" className="inline-block h-1 w-3 bg-danger" />
              <span className="text-text-secondary">Failed</span>
              <span className="tabular-nums">{n(failed)}</span>
            </li>
          ) : null}
        </ul>
        {summary?.steps_cut ? (
          <p className="text-xs text-text-muted">
            The bar shows the first {n(steps.length)} steps; the counts are for the whole session.
          </p>
        ) : null}
      </figcaption>
    </figure>
  );
}
