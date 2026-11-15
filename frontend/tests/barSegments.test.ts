import { describe, expect, it } from "vitest";
import type { SessionStep } from "@/lib/api";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  hasTick,
  markStyle,
  MAX_SEGMENTS,
  segmentMark,
  segments,
  TYPES,
} from "@/features/ai/barSegments";

let id = 0;
function step(type: SessionStep["type"] | undefined, event = "pre_tool_use"): SessionStep {
  id += 1;
  return {
    time: new Date(Date.UTC(2026, 9, 22, 18, 0, id)).toISOString(),
    event,
    role: null,
    tool: "Read",
    mcp_server: null,
    mcp_tool: null,
    path: null,
    web_host: null,
    program: null,
    prompt_chars: null,
    input_chars: null,
    output_chars: null,
    event_id: `e${id}`,
    ...(type ? { type } : {}),
  };
}

describe("The session timeline bar's segments", () => {
  it("keeps the steps' order and type, one run of the same type a segment", () => {
    const steps = [
      step("other", "session_start"),
      step("prompt", "user_prompt_submit"),
      step("file_access"),
      step("tool_result", "post_tool_use"),
      step("tool_result", "post_tool_use"),
      step("access"),
      step(undefined, "stop"), // an older server sends no type: other
    ];
    const got = segments(steps);
    expect(got.map((s) => [s.type, s.count])).toEqual([
      ["other", 1],
      ["prompt", 1],
      ["file_access", 1],
      ["tool_result", 2],
      ["access", 1],
      ["other", 1],
    ]);
    expect(got[3]!.first).toBe(steps[3]!.event_id);
    expect(got[3]!.ids).toEqual([steps[3]!.event_id, steps[4]!.event_id]);
  });

  it("marks a failed result apart from the results around it", () => {
    const steps = [
      step("tool_result", "post_tool_use"),
      step("tool_result", "post_tool_use_failure"),
      step("tool_result", "post_tool_use"),
    ];
    expect(segments(steps).map((s) => [s.count, s.failed])).toEqual([
      [1, false],
      [1, true],
      [1, false],
    ]);
  });

  it("cuts a long session into equal slices drawn in their most common type", () => {
    // 2,000 steps alternating call and result: no runs to merge.
    const steps = Array.from({ length: 2000 }, (_, i) =>
      i % 2
        ? step("tool_result", i === 1001 ? "post_tool_use_failure" : "post_tool_use")
        : step("tool_call"),
    );
    // Make the first slice mostly prompts.
    for (let i = 0; i < 5; i++) steps[i] = step("prompt", "user_prompt_submit");
    const got = segments(steps);
    expect(got).toHaveLength(MAX_SEGMENTS);
    expect(got.reduce((a, s) => a + s.count, 0)).toBe(2000);
    expect(got[0]!.type).toBe("prompt");
    expect(got[0]!.types).toEqual({ prompt: 5, tool_result: 1, tool_call: 1 });
    expect(got.filter((s) => s.failed)).toHaveLength(1);
    expect(got.every((s) => s.count >= 7 && s.count <= 8)).toBe(true);
  });

  it("draws two colors and the neutral, and hatches what reached outside the session", () => {
    const by = Object.fromEntries(TYPES.map((t) => [t.type, t]));
    // Solid marks are an inline background from the series variable, never a class the
    // built CSS might not hold.
    expect(
      [by.prompt, by.tool_call, by.tool_result].map((t) => markStyle(t!).style.background),
    ).toEqual(["var(--series-ice)", "var(--series-graphite)", "var(--series-neutral)"]);
    expect(TYPES.every((t) => markStyle(t).className === "" || t.type === "other")).toBe(true);
    // Hatched: solid top half over diagonal stripes, so a 2px segment still differs by shape.
    for (const [type, color] of [
      ["file_access", "series-graphite"],
      ["access", "series-ice"],
    ] as const) {
      const bg = markStyle(by[type]!).style.background ?? "";
      expect(bg).toContain(
        `linear-gradient(var(--${color}), var(--${color})) top / 100% 50% no-repeat`,
      );
      expect(bg).toContain(`repeating-linear-gradient(135deg, var(--${color}) 0 1.5px`);
    }
    expect(markStyle(by.other!)).toEqual({ className: "border border-text-muted", style: {} });
    // No type has a color of its own outside the three series.
    expect(new Set(TYPES.map((t) => t.color))).toEqual(
      new Set(["series-ice", "series-graphite", "series-neutral", null]),
    );
  });

  it("draws a slice exactly as the legend shows its majority type, and ticks any outside step", () => {
    // 2,000 steps, so 280 slices of 7 or 8; slice 0 is steps 0 to 6.
    const slice = (major: SessionStep["type"], withOutside: boolean) => {
      // Alternating filler, so there are far more runs than segments and the bar slices.
      const steps = Array.from({ length: 2000 }, (_, i) =>
        i % 2 ? step("tool_result", "post_tool_use") : step("tool_call"),
      );
      for (let i = 0; i < 5; i++) steps[i] = step(major, "pre_tool_use");
      steps[5] = withOutside
        ? step(major === "access" ? "file_access" : "access")
        : step("tool_result", "post_tool_use");
      return segments(steps)[0]!;
    };
    for (const t of TYPES) {
      for (const withOutside of [false, true]) {
        const seg = slice(t.type, withOutside);
        expect(seg.count).toBeGreaterThan(1); // a slice, not a run
        expect(seg.type).toBe(t.type);
        // The fill is the legend's own mark for that type, through the same function.
        expect(markStyle(segmentMark(seg))).toEqual(markStyle(t));
        expect(hasTick(seg)).toBe(withOutside || t.type === "file_access" || t.type === "access");
      }
    }
    // A slice drawn as Other that holds an outside step: a hollow outline, and the tick.
    const other = slice("other", true);
    expect(markStyle(segmentMark(other))).toEqual({
      className: "border border-text-muted",
      style: {},
    });
    expect(hasTick(other)).toBe(true);
    // A run of one file access or access carries the tick too: it always means "here".
    expect(hasTick(segments([step("access")])[0]!)).toBe(true);
    expect(hasTick(segments([step("tool_call")])[0]!)).toBe(false);
  });

  it("keeps fills when printed and leaves forced colors to the system", () => {
    const style = markStyle(TYPES[0]!).style;
    expect(style).not.toHaveProperty("forcedColorAdjust");
    expect(style.printColorAdjust).toBe("exact");
    const css = readFileSync(resolve(__dirname, "../src/styles/globals.css"), "utf8");
    const forced = css.slice(css.lastIndexOf("@media (forced-colors: active)"));
    // Scoped to the bar: other charts that draw the neutral series keep their colors.
    expect(forced).toMatch(/\[data-session-bar\] \{/);
    expect(forced).not.toMatch(/html:root/);
    expect(forced).toMatch(/--series-ice: CanvasText;/);
    expect(forced).toMatch(/--series-graphite: CanvasText;/);
    expect(forced).toMatch(/--series-neutral: CanvasText;/);
  });
});
