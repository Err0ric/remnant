import type { SessionStep } from "@/lib/api";

/** A session's steps grouped by turn (owner, 2026-11-03): the prompt, then the tool calls
 * it led to, each with its result, then how the turn ended. Hook records carry no id that
 * ties a result to its call, so a result goes to the earliest call to the same tool (and
 * MCP server) in the turn that has none yet. */

export interface ToolCall {
  call: SessionStep | null; // null: a result whose call was not recorded
  result: SessionStep | null; // null: no result (blocked, interrupted, or still running)
}

export type TurnEnd = "finished" | "interrupted" | "open";

export interface Turn {
  prompt: SessionStep | null; // null: what came before the first prompt
  calls: ToolCall[];
  end: TurnEnd;
  endedAt: string | null;
}

export interface Grouped {
  started: SessionStep | null;
  turns: Turn[];
  ended: SessionStep | null;
}

const CALL = "pre_tool_use";
const RESULTS = new Set(["post_tool_use", "post_tool_use_failure"]);

function key(s: SessionStep): string {
  return `${s.mcp_server ?? ""}|${s.tool ?? ""}`;
}

function base(e: string): string {
  return e.replace(/^claude_hooks\./, "");
}

export function groupTurns(steps: SessionStep[]): Grouped {
  const out: Grouped = { started: null, turns: [], ended: null };
  let turn: Turn | null = null;
  const open = () => {
    if (turn === null) {
      turn = { prompt: null, calls: [], end: "open", endedAt: null };
      out.turns.push(turn);
    }
    return turn;
  };
  for (const s of steps) {
    const e = base(s.event);
    if (e === "session_start") {
      out.started ??= s;
    } else if (e === "session_end") {
      if (turn !== null && (turn as Turn).end === "open") (turn as Turn).end = "interrupted";
      out.ended = s;
    } else if (e === "user_prompt_submit") {
      // A new prompt before a turn end: the turn before was interrupted.
      if (turn !== null && (turn as Turn).end === "open") (turn as Turn).end = "interrupted";
      turn = { prompt: s, calls: [], end: "open", endedAt: null };
      out.turns.push(turn);
    } else if (e === "stop") {
      const t = open();
      t.end = "finished";
      t.endedAt = s.time;
      turn = null; // the next call without a prompt starts its own group
    } else if (e === CALL) {
      open().calls.push({ call: s, result: null });
    } else if (RESULTS.has(e)) {
      const t = open();
      const waiting = t.calls.find((c) => c.result === null && c.call && key(c.call) === key(s));
      if (waiting) waiting.result = s;
      else t.calls.push({ call: null, result: s });
    }
  }
  return out;
}
