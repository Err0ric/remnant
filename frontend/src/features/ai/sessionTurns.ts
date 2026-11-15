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
  /** The turn end record, when there is one. */
  endStep?: SessionStep;
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
      t.endStep = s;
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

/** What a turn led to, in one line: "5 tool calls: Read 3, Bash 2" (an MCP call by its
 * server), most used first, a tie by name. */
export function ledTo(turn: Turn): string {
  const n = turn.calls.length;
  if (n === 0) return "No tool calls";
  const by = new Map<string, number>();
  for (const c of turn.calls) {
    const s = (c.call ?? c.result)!;
    const name = s.mcp_server ?? s.tool ?? "Unknown tool";
    by.set(name, (by.get(name) ?? 0) + 1);
  }
  const parts = [...by].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  return `${n} tool ${n === 1 ? "call" : "calls"}: ${parts.map(([k, v]) => `${k} ${v}`).join(", ")}`;
}

/** The steps a session's flags point at (D188), by event id: a failed result, a call with
 * no result once the session is not open, and a call to an MCP server first used in it.
 * Claude Code bookkeeping is never flagged: the server marks it (`counted`), by the rule its
 * counts use (D186). With `cut` (the list stops before the session's end), a call in a last
 * turn that has not ended may have its result past the cut: never flagged as unanswered. */
export function flaggedSteps(
  steps: SessionStep[],
  open: boolean,
  newMcp: string[],
  cut = false,
): Set<string> {
  const out = new Set<string>();
  const turns = groupTurns(steps).turns;
  turns.forEach((t, i) => {
    const mayContinue = cut && i === turns.length - 1 && t.end !== "finished";
    for (const c of t.calls) {
      if ((c.call ?? c.result)?.counted === false) continue;
      if (c.result && base(c.result.event) === "post_tool_use_failure") {
        out.add(c.result.event_id);
        if (c.call) out.add(c.call.event_id);
      }
      if (c.call && c.result === null && !open && !mayContinue) out.add(c.call.event_id);
      if (c.call?.mcp_server && newMcp.includes(c.call.mcp_server)) out.add(c.call.event_id);
    }
  });
  return out;
}
