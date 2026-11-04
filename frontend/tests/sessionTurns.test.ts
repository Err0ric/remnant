import { describe, expect, it } from "vitest";
import { groupTurns } from "@/features/ai/sessionTurns";
import type { SessionStep } from "@/lib/api";

let n = 0;
function step(event: string, tool: string | null = null, mcp: string | null = null): SessionStep {
  n += 1;
  return {
    time: `2026-10-10T10:00:${String(n).padStart(2, "0")}+00:00`,
    event,
    role: null,
    tool,
    mcp_server: mcp,
    mcp_tool: null,
    path: null,
    web_host: null,
    program: null,
    prompt_chars: null,
    input_chars: null,
    output_chars: null,
    event_id: `e${n}`,
  };
}

describe("groupTurns (D187)", () => {
  it("puts each result under its call, drops turn ends, and says how each turn ended", () => {
    const g = groupTurns([
      step("session_start"),
      step("user_prompt_submit"),
      step("pre_tool_use", "Read"),
      step("pre_tool_use", "Bash"),
      step("pre_tool_use", "Read"),
      step("post_tool_use", "Read"), // the first Read
      step("post_tool_use_failure", "Bash"),
      step("stop"),
      step("user_prompt_submit"),
      step("pre_tool_use", "Edit"), // never answered: the next prompt comes first
      step("user_prompt_submit"),
      step("post_tool_use", "Grep"), // a result whose call was not recorded
      step("session_end"),
    ]);
    expect(g.started?.event).toBe("session_start");
    expect(g.ended?.event).toBe("session_end");
    expect(g.turns.map((t) => t.end)).toEqual(["finished", "interrupted", "interrupted"]);
    const [first, second, third] = g.turns;
    expect(first!.calls.map((c) => [c.call?.tool, c.result?.event ?? null])).toEqual([
      ["Read", "post_tool_use"],
      ["Bash", "post_tool_use_failure"],
      ["Read", null], // no result: blocked, interrupted, or still running
    ]);
    expect(first!.endedAt).not.toBeNull();
    expect(second!.calls).toEqual([
      { call: expect.objectContaining({ tool: "Edit" }), result: null },
    ]);
    expect(third!.calls).toEqual([
      { call: null, result: expect.objectContaining({ tool: "Grep" }) },
    ]);
  });

  it("keeps a last turn with no end open", () => {
    const g = groupTurns([step("user_prompt_submit"), step("pre_tool_use", "Read")]);
    expect(g.turns).toHaveLength(1);
    expect(g.turns[0]!.end).toBe("open");
  });

  it("matches MCP results by server too", () => {
    const g = groupTurns([
      step("user_prompt_submit"),
      step("pre_tool_use", "mcp__a__x", "a"),
      step("pre_tool_use", "mcp__a__x", "b"),
      step("post_tool_use", "mcp__a__x", "b"),
    ]);
    expect(g.turns[0]!.calls.map((c) => [c.call?.mcp_server, c.result !== null])).toEqual([
      ["a", false],
      ["b", true],
    ]);
  });
});
