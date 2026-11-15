import { describe, expect, it } from "vitest";
import type { SessionStep } from "@/lib/api";
import { MAX_SEGMENTS, segments } from "@/features/ai/barSegments";

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
});
