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
}

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
    } else {
      runs.push({
        type: t,
        count: 1,
        first: s.event_id,
        ids: [s.event_id],
        failed: isFailed(s),
        types: { [t]: 1 },
      });
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
    });
  }
  return out;
}

/** The five step types and their series colors (DESIGN.md section 2); other is a hollow
 * outline in --text-muted, never a sixth color. */
export const TYPES: { type: StepType; label: string; fill: string }[] = [
  { type: "prompt", label: "Prompt", fill: "bg-series-1" },
  { type: "tool_call", label: "Tool call", fill: "bg-series-2" },
  { type: "tool_result", label: "Tool result", fill: "bg-series-neutral" },
  { type: "file_access", label: "File access", fill: "bg-series-3" },
  { type: "access", label: "Access", fill: "bg-series-4" },
  { type: "other", label: "Other", fill: "border border-text-muted" },
];
