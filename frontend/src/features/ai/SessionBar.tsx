import { When } from "@/components/When";
import type { SessionStep, SessionSummary } from "@/lib/api";
import { cn } from "@/lib/cn";
import {
  HATCH_MEANS,
  isFailed,
  hasTick,
  markStyle,
  segmentMark,
  TICK_MEANS,
  segments,
  TYPES,
  type Segment,
  type TypeMark,
} from "./barSegments";

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
/** "Web or MCP access" as "web or MCP access": only the first letter, so MCP stays MCP. */
const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);
/** The step types that are tool calls: together the session's Tool calls (the server leaves
 * Claude Code bookkeeping out of all three, D186). */
const CALL_TYPES: ReadonlySet<string> = new Set(["tool_call", "file_access", "access"]);
/** In the legend, under "Tool calls": a plain call is the one that stayed in the session. */
const CALL_LABEL: Partial<Record<string, string>> = { tool_call: "In the session" };

/** One legend entry: the type's mark, its name, and its count. */
function Entry({ t, label, count }: { t: TypeMark; label: string; count: number }) {
  return (
    <li className="flex items-center gap-1.5">
      <span
        aria-hidden="true"
        data-mark={t.type}
        className={cn("inline-block h-4 w-4", markStyle(t).className)}
        style={markStyle(t).style}
      />
      <span className="text-text-secondary">{label}</span>
      <span className="tabular-nums">{n(count)}</span>
    </li>
  );
}
const LABEL = Object.fromEntries(TYPES.map((t) => [t.type, t.label])) as Record<string, string>;

/** True for a run and for a mixed slice alike. */
function outsideNote(seg: Segment): string {
  if (seg.outside === 0) return "";
  if (seg.outside === seg.count) return "; reached outside the session";
  return `; ${n(seg.outside)} of these steps reached outside the session`;
}

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
    ? TYPES.map((t) => `${n(counts[t.type] ?? 0)} ${lower(t.label)}`).join(", ")
    : `${n(steps.length)} steps`;
  const failed = summary?.failed ?? steps.filter(isFailed).length;
  const outside = counts
    ? (counts.file_access ?? 0) + (counts.access ?? 0)
    : steps.filter((s) => s.type === "file_access" || s.type === "access").length;
  // The whole session's count from the server; the loaded steps while it is not there.
  const of = (t: TypeMark) =>
    counts ? (counts[t.type] ?? 0) : steps.filter((s) => (s.type ?? "other") === t.type).length;
  const listed = new Set(shown.map((s) => s.event_id));
  const order = new Map(steps.map((s, i) => [s.event_id, i]));
  const after = (id: string) =>
    shown.find((s) => (order.get(s.event_id) ?? -1) > (order.get(id) ?? Infinity))?.event_id ??
    null;
  // A 1px gap between segments only while there is room for it: a sliced session has up to
  // 280 segments, and gaps plus a minimum width would make the bar wider than a phone-width
  // pane. The three rows share the rule, so a failed notch above and a tick below always
  // line up with their segment.
  const row = cn("flex min-w-0 overflow-hidden", segs.length <= 140 && "gap-px");
  return (
    <figure className="grid min-w-0 gap-1" aria-label="Session timeline bar" data-session-bar>
      <div
        role="img"
        aria-label={`Session timeline: ${spoken}${failed ? `, ${n(failed)} failed` : ""}${outside ? `, ${n(outside)} reached outside the session` : ""}${summary?.steps_cut ? `; the bar shows the first ${n(steps.length)} steps` : ""}`}
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
            const mark = segmentMark(s);
            const drawn = markStyle(mark);
            return (
              <span
                key={s.first}
                data-segment={s.type}
                data-hatched={mark.hatch || undefined}
                data-opens={target ?? undefined}
                title={`${hover(s)}${outsideNote(s)}${off ? (flagged !== null ? " (not flagged)" : " (not listed in this view)") : ""}`}
                style={{ ...drawn.style, flexGrow: s.count, flexBasis: 0 }}
                onClick={off ? undefined : () => onPick(target)}
                className={cn(
                  "min-w-0",
                  drawn.className,
                  off ? "opacity-25" : "cursor-pointer hover:opacity-80",
                )}
              />
            );
          })}
        </div>
        <div className={cn(row, "h-1")} data-bar="ticks" aria-hidden="true">
          {segs.map((s) => (
            <span
              key={s.first}
              data-tick={hasTick(s) || undefined}
              style={{
                flexGrow: s.count,
                flexBasis: 0,
                ...(hasTick(s) ? { background: "var(--text-secondary)" } : {}),
              }}
              className="min-w-0"
            />
          ))}
        </div>
      </div>
      <div className="flex justify-between text-xs text-text-muted">
        <When iso={steps[0]!.time} />
        <When iso={steps[steps.length - 1]!.time} />
      </div>
      <figcaption>
        <ul aria-label="Step types" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          {TYPES.filter((t) => !CALL_TYPES.has(t.type)).map((t) => (
            <Entry key={t.type} t={t} label={t.label} count={of(t)} />
          ))}
          {failed ? (
            <li className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                data-failed="legend"
                className="inline-block h-1 w-3 bg-danger"
              />
              <span className="text-text-secondary">Failed</span>
              <span className="tabular-nums">{n(failed)}</span>
            </li>
          ) : null}
          {/* The three kinds of tool call under one total, the session's Tool calls (fix
              list S3), on a row of their own so the group never splits or strands a type. */}
          <li data-legend="tool_calls" className="flex w-full flex-wrap items-center gap-x-3">
            <span className="whitespace-nowrap">
              <span className="text-text-secondary">Tool calls</span>{" "}
              <span className="tabular-nums">
                {n(TYPES.filter((c) => CALL_TYPES.has(c.type)).reduce((a, c) => a + of(c), 0))}
              </span>
              :
            </span>
            <ul
              aria-label="Tool calls by kind"
              className="flex flex-wrap gap-x-4 gap-y-1 border-l border-border pl-3"
            >
              {TYPES.filter((c) => CALL_TYPES.has(c.type)).map((c) => (
                <Entry key={c.type} t={c} label={CALL_LABEL[c.type] ?? c.label} count={of(c)} />
              ))}
            </ul>
          </li>
        </ul>
        <p className="text-xs text-text-muted">{HATCH_MEANS}.</p>
        <p className="flex items-center gap-1.5 text-xs text-text-muted">
          <span
            aria-hidden="true"
            data-tick="legend"
            className="inline-block h-1 w-3"
            style={{ background: "var(--text-secondary)" }}
          />
          {TICK_MEANS}.
        </p>
        {summary?.steps_cut ? (
          <p className="text-xs text-text-muted">
            The bar shows the first {n(steps.length)} steps; the counts are for the whole session.
          </p>
        ) : null}
      </figcaption>
    </figure>
  );
}
