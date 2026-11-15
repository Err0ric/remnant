import type { SessionStep } from "@/lib/api";
import { cn } from "@/lib/cn";
import { zoneIfRepeated } from "@/lib/localTime";
import { stamp } from "@/features/overview/time";
import { groupTurns, ledTo, type ToolCall, type Turn } from "./sessionTurns";

/** "3 h", "2 d": how late a queued step arrived. */
export function late(seconds: number): string {
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h`;
  return `${Math.round(seconds / 86400)} d`;
}

/** What a step touched, in one line: the file, the web host, the program, the MCP tool. */
function target(s: SessionStep): string {
  if (s.mcp_server) return `${s.mcp_server} ${s.mcp_tool ?? ""}`.trim();
  return s.path ?? s.web_host ?? s.program ?? "";
}

function size(s: SessionStep): string {
  if (s.prompt_chars) return `${s.prompt_chars.toLocaleString()} chars`;
  if (s.output_chars) return `${s.output_chars.toLocaleString()} chars out`;
  if (s.input_chars) return `${s.input_chars.toLocaleString()} chars in`;
  return "";
}

const failedStep = (s: SessionStep | null) => s?.event.endsWith("failure") ?? false;

/** The server's step type in plain words (app.ai.sessions.step_type); "other" by event. */
const TYPE_LABEL: Record<string, string> = {
  prompt: "Prompt",
  tool_call: "Tool call",
  tool_result: "Tool result",
  file_access: "File access",
  access: "Access",
};
const OTHER_LABEL: Record<string, string> = {
  session_start: "Session started",
  stop: "Turn end",
  session_end: "Session ended",
};
function typeLabel(s: SessionStep): string {
  const t = s.type ? TYPE_LABEL[s.type] : undefined;
  return t ?? OTHER_LABEL[s.event.replace(/^claude_hooks\./, "")] ?? "Other";
}

/** A step's time in the viewer's zone with seconds, the UTC time on hover (as When). */
function StepTime({ iso }: { iso: string }) {
  const d = new Date(iso);
  const text = d.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
  return (
    <time
      dateTime={iso}
      title={`${stamp(iso)} UTC`}
      className="font-mono text-text-muted tabular-nums"
    >
      {text}
      {zoneIfRepeated(d)}
    </time>
  );
}

export interface StepsProps {
  steps: SessionStep[];
  /** Event ids of flagged steps; with `flaggedOnly`, only those (and their turns) show. */
  flagged: Set<string>;
  flaggedOnly: boolean;
  around: SessionStep | null;
  onAround: (s: SessionStep | null) => void;
}

function AroundButton({
  st,
  around,
  onAround,
}: Pick<StepsProps, "around" | "onAround"> & {
  st: SessionStep;
}) {
  const on = around?.event_id === st.event_id;
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={`Around this step at ${new Date(st.time).toLocaleTimeString("en-US")}`}
      onClick={() => onAround(on ? null : st)}
      className={cn(
        "text-xs text-accent-text hover:underline focus:opacity-100 group-hover:opacity-100 max-sm:col-start-3 max-sm:row-start-1",
        on ? "opacity-100" : "opacity-0",
      )}
    >
      Around
    </button>
  );
}

// On a phone the size goes under what the step touched, so neither is squeezed.
/** A row the timeline bar can open: the step ids it stands for, focusable from code only. */
const pick = (...steps: (SessionStep | null | undefined)[]) => ({
  "data-steps": steps
    .filter((s): s is SessionStep => !!s)
    .map((s) => s.event_id)
    .join(" "),
  tabIndex: -1,
});

const ROW =
  "group grid grid-cols-[6.5rem_minmax(0,1fr)_auto] items-baseline gap-x-3 py-0.5 text-sm sm:grid-cols-[6.5rem_minmax(0,1fr)_auto_auto]";
const SIZE = "text-text-muted tabular-nums max-sm:col-start-2 max-sm:row-start-2";

/** Execution: every step in order, one row each: time, type, tool, what it touched, size. */
/** A tool call row of Conversation is shown under Flagged only when its call or result is
 * flagged. */
const hitBy = (flagged: Set<string>) => (c: ToolCall) =>
  [c.call, c.result].some((s) => s !== null && flagged.has(s.event_id));

/** The steps that have a row in the view now, in order: what the bar can open. One rule
 * with the two views below. */
export function shownSteps(
  steps: SessionStep[],
  view: "execution" | "conversation",
  flagged: Set<string>,
  flaggedOnly: boolean,
): SessionStep[] {
  if (view === "execution")
    return flaggedOnly ? steps.filter((s) => flagged.has(s.event_id)) : steps;
  const g = groupTurns(steps);
  const hit = hitBy(flagged);
  const out: (SessionStep | null | undefined)[] = [];
  if (!flaggedOnly) out.push(g.started);
  for (const t of flaggedOnly ? g.turns.filter((t) => t.calls.some(hit)) : g.turns) {
    out.push(t.prompt);
    for (const c of flaggedOnly ? t.calls.filter(hit) : t.calls) out.push(c.call, c.result);
    out.push(t.endStep);
  }
  if (!flaggedOnly) out.push(g.ended);
  const ids = new Set(out.filter((s): s is SessionStep => !!s).map((s) => s.event_id));
  return steps.filter((s) => ids.has(s.event_id));
}

export function ExecutionSteps({ steps, flagged, flaggedOnly, around, onAround }: StepsProps) {
  const shown = shownSteps(steps, "execution", flagged, flaggedOnly);
  return (
    <ol aria-label="Session steps" className="flex flex-col">
      {shown.map((st) => {
        const what = target(st);
        return (
          <li key={st.event_id} className={ROW} {...pick(st)}>
            <StepTime iso={st.time} />
            <span className="min-w-0 truncate" title={what || undefined}>
              <span className="inline-block w-24 text-text-secondary">{typeLabel(st)}</span>
              {st.tool || st.mcp_server ? (
                <span className="font-mono">{st.mcp_server ? "MCP" : st.tool}</span>
              ) : null}
              {failedStep(st) ? <span className="text-warn"> Failed</span> : null}
              {what ? <span className="font-mono text-text-secondary"> {what}</span> : null}
            </span>
            <span className={SIZE}>
              {[
                size(st),
                st.late_s ? `delivered ${late(st.late_s)} late` : "",
                flagged.has(st.event_id) ? "Flagged" : "",
              ]
                .filter(Boolean)
                .join(", ")}
            </span>
            <AroundButton st={st} around={around} onAround={onAround} />
          </li>
        );
      })}
    </ol>
  );
}

const END: Record<Turn["end"], string> = {
  finished: "Finished",
  interrupted: "Interrupted: no turn end before the next prompt or the session end",
  open: "No turn end yet (still running, or interrupted)",
};

/** Conversation: by turn (owner, 2026-11-03; D187): the prompt, what it led to, the tool
 * calls under it each with its result, then how the turn ended. */
export function ConversationSteps({ steps, flagged, flaggedOnly, around, onAround }: StepsProps) {
  const g = groupTurns(steps);
  const hit = hitBy(flagged);
  const turns = flaggedOnly ? g.turns.filter((t) => t.calls.some(hit)) : g.turns;
  const edge = (st: SessionStep | null, text: string) =>
    st && !flaggedOnly ? (
      <li className={cn(ROW, "border-t border-border pt-1")} {...pick(st)}>
        <StepTime iso={st.time} />
        <span className="text-text-secondary">{text}</span>
        <span />
        <AroundButton st={st} around={around} onAround={onAround} />
      </li>
    ) : null;
  return (
    <ol aria-label="Session timeline" className="flex flex-col gap-2">
      {edge(g.started, "Session started")}
      {turns.map((t, i) => {
        const failed = t.calls.filter((c) => failedStep(c.result)).length;
        return (
          <li key={t.prompt?.event_id ?? `turn-${i}`} className="border-t border-border pt-1">
            <ol aria-label={`Turn ${i + 1}`} className="flex flex-col">
              {t.prompt ? (
                <li className={ROW} {...pick(t.prompt)}>
                  <StepTime iso={t.prompt.time} />
                  <span className="min-w-0 truncate">
                    <span className="font-semibold">Prompt</span>{" "}
                    <span className="text-text-secondary">{ledTo(t)}</span>
                  </span>
                  <span className={SIZE}>{size(t.prompt)}</span>
                  <AroundButton st={t.prompt} around={around} onAround={onAround} />
                </li>
              ) : null}
              {(flaggedOnly ? t.calls.filter(hit) : t.calls).map((c) => (
                <CallRow
                  key={(c.call ?? c.result)!.event_id}
                  c={c}
                  around={around}
                  onAround={onAround}
                />
              ))}
              <li className={cn(ROW, "text-text-secondary")} {...pick(t.endStep)}>
                {t.endedAt ? <StepTime iso={t.endedAt} /> : <span />}
                <span>
                  {END[t.end]}
                  {t.calls.length
                    ? `, ${t.calls.length} tool ${t.calls.length === 1 ? "call" : "calls"}`
                    : ""}
                  {failed ? `, ${failed} failed` : ""}
                </span>
                <span />
                <span />
              </li>
            </ol>
          </li>
        );
      })}
      {edge(g.ended, "Session ended")}
    </ol>
  );
}

function CallRow({
  c,
  around,
  onAround,
}: { c: ToolCall } & Pick<StepsProps, "around" | "onAround">) {
  const st = (c.call ?? c.result)!;
  const failed = failedStep(c.result);
  const what = target(c.call ?? st) || (c.result ? target(c.result) : "");
  const sz = c.result ? size(c.result) : size(st);
  const lateBy = c.result?.late_s ?? st.late_s;
  return (
    <li className={ROW} {...pick(c.call, c.result)}>
      <StepTime iso={st.time} />
      {/* The result first, the path last: a long path never hides how the call went. */}
      <span className="min-w-0 truncate pl-4" title={what}>
        <span className="font-mono">{st.mcp_server ? "MCP" : st.tool}</span>{" "}
        {c.result === null ? (
          <span className="text-text-muted">
            No result (blocked, interrupted, or still running)
          </span>
        ) : failed ? (
          <span className="text-warn">Failed</span>
        ) : c.call === null ? (
          <span className="text-text-secondary">Returned (call not recorded)</span>
        ) : (
          <span className="text-text-secondary">Returned</span>
        )}
        {what ? <span className="font-mono text-text-secondary"> {what}</span> : null}
      </span>
      <span className={SIZE}>
        {[sz, lateBy ? `delivered ${late(lateBy)} late` : ""].filter(Boolean).join(", ")}
      </span>
      <AroundButton st={st} around={around} onAround={onAround} />
    </li>
  );
}
