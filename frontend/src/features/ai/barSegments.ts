import type { SessionStep } from "@/lib/api";

export type StepType = NonNullable<SessionStep["type"]>;

/** At most this many segments; past it the steps are cut into this many equal slices. At
 * a desktop pane's narrowest (about 560px) that keeps a segment near 2px wide; on a phone
 * the segments share the width with no gaps (`SessionBar`). */
export const MAX_SEGMENTS = 280;

export interface Segment {
  /** The type drawn: the run's, or the most common in a slice (ties by order). */
  type: StepType;
  /** Steps in the segment; its width is this count, so every step is the same width. */
  count: number;
  /** The first step, which a click opens below. */
  first: string;
  /** Every step's event id, for flagged and failed checks. */
  ids: string[];
  failed: boolean;
  /** Steps per type, for the hover text of a slice. */
  types: Partial<Record<StepType, number>>;
  /** Steps that reached outside the session (file access, access): any of them puts a tick
   * under the segment, whatever type it is drawn in (D264). */
  outside: number;
}

const OUTSIDE: ReadonlySet<StepType> = new Set(["file_access", "access"]);

const typeOf = (s: SessionStep): StepType => s.type ?? "other";
/** A failed call, by the rule the server's failed count uses: Claude Code bookkeeping
 * (`counted` false, D186) is never a failure. */
export const isFailed = (s: SessionStep) =>
  s.event.endsWith("post_tool_use_failure") && s.counted !== false;

/** The bar's segments, in order, equal width per step (tool calls are instants, and idle
 * gaps would hide them if drawn by time). Up to MAX_SEGMENTS: one segment per run of steps
 * of the same type and failure. More: MAX_SEGMENTS equal slices, each drawn in the type
 * most of its steps have, failed when any of them failed. */
export function segments(steps: SessionStep[]): Segment[] {
  const runs: Segment[] = [];
  for (const s of steps) {
    const t = typeOf(s);
    const last = runs[runs.length - 1];
    if (last && last.type === t && last.failed === isFailed(s)) {
      last.count += 1;
      last.ids.push(s.event_id);
      last.types[t] = (last.types[t] ?? 0) + 1;
      last.outside += OUTSIDE.has(t) ? 1 : 0;
    } else {
      runs.push({
        type: t,
        count: 1,
        first: s.event_id,
        ids: [s.event_id],
        failed: isFailed(s),
        types: { [t]: 1 },
        outside: 0,
      });
      runs[runs.length - 1]!.outside = OUTSIDE.has(t) ? 1 : 0;
    }
  }
  if (runs.length <= MAX_SEGMENTS) return runs;
  const out: Segment[] = [];
  const size = steps.length / MAX_SEGMENTS;
  for (let i = 0; i < MAX_SEGMENTS; i++) {
    const part = steps.slice(Math.round(i * size), Math.round((i + 1) * size));
    if (part.length === 0) continue;
    const types: Partial<Record<StepType, number>> = {};
    for (const s of part) types[typeOf(s)] = (types[typeOf(s)] ?? 0) + 1;
    const type = (Object.entries(types) as [StepType, number][]).reduce((a, b) =>
      b[1] > a[1] ? b : a,
    )[0];
    out.push({
      type,
      count: part.length,
      first: part[0]!.event_id,
      ids: part.map((s) => s.event_id),
      failed: part.some(isFailed),
      types,
      outside: part.filter((s) => OUTSIDE.has(typeOf(s))).length,
    });
  }
  return out;
}

export interface TypeMark {
  type: StepType;
  label: string;
  /** The series token the mark is drawn in; none for other, a hollow outline. */
  color: "series-ice" | "series-graphite" | "series-neutral" | null;
  /** Hatched: the step reached outside the session (a file, the web, an MCP server). */
  hatch: boolean;
}

/** The step types and their marks (DESIGN.md section 2 and 6.2b, D264): prompts ice, tool
 * calls graphite, tool results the neutral; a file access is hatched graphite and an access
 * hatched ice, since both reached outside the session; other is a hollow --text-muted
 * outline. The hatch works with no color at all. */
export const TYPES: TypeMark[] = [
  { type: "prompt", label: "Prompt", color: "series-ice", hatch: false },
  { type: "tool_call", label: "Tool call", color: "series-graphite", hatch: false },
  { type: "tool_result", label: "Tool result", color: "series-neutral", hatch: false },
  { type: "file_access", label: "File access", color: "series-graphite", hatch: true },
  { type: "access", label: "Web or MCP access", color: "series-ice", hatch: true },
  { type: "other", label: "Other", color: null, hatch: false },
];

export const HATCH_MEANS =
  "Hatched: a file access or a web or MCP access, the steps that reach outside the session";

export const TICK_MEANS =
  "Tick below: at least one step in this part of the bar reached outside the session (a file, the web, or an MCP server)";

type Mark = Pick<TypeMark, "color" | "hatch">;

/** How a type's mark is drawn, the same in the bar and the legend, always as an inline
 * background from the series variable (never a generated class the build may not emit).
 * A hatched mark is solid in its top half and diagonal stripes in its bottom half, so it
 * differs from its solid sibling at every width. `print-color-adjust: exact` keeps the fills
 * when printed (browsers drop backgrounds by default). On a forced-colors display the series
 * variables become CanvasText (globals.css), so the marks keep system contrast and differ by
 * the hatch and the tick only. Other is a hollow outline. */
export function markStyle(t: Mark): { className: string; style: Record<string, string> } {
  if (t.color === null) return { className: "border border-text-muted", style: {} };
  const c = `var(--${t.color})`;
  return {
    className: "",
    style: {
      printColorAdjust: "exact",
      WebkitPrintColorAdjust: "exact",
      background: t.hatch
        ? `linear-gradient(${c}, ${c}) top / 100% 50% no-repeat, repeating-linear-gradient(135deg, ${c} 0 1.5px, transparent 1.5px 4px)`
        : c,
    },
  };
}

export const markOf = (type: StepType): TypeMark => TYPES.find((t) => t.type === type) ?? TYPES[5]!;

/** A segment is drawn exactly as the legend shows its type (a slice: its majority type),
 * nothing else; whether anything in it reached outside is the tick's to say. */
export const segmentMark = (seg: Segment): Mark => markOf(seg.type);

/** The tick under a segment: at least one of its steps reached outside the session, for a
 * slice whatever its majority type, and for a run of file accesses or accesses alike. */
export const hasTick = (seg: Segment): boolean => seg.outside > 0;
