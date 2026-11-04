import { EntityLink } from "@/components/EntityLink";
import { When } from "@/components/When";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { AroundEvent } from "@/features/search/AroundEvent";
import { ApiError, api, type AgentAccount, type AgentSession, type SessionStep } from "@/lib/api";
import { cn } from "@/lib/cn";
import { TIER_LABEL, TierBadge } from "./AccountsCard";
import { since, stamp } from "@/features/overview/time";
import { groupTurns, type ToolCall, type Turn } from "./sessionTurns";
import { zoneIfRepeated } from "@/lib/localTime";
import { SectionTitle } from "@/components/SectionTitle";
import { PanelTitle } from "@/components/PanelTitle";
import { duration, FLAG_LABEL, sessionFlags, type SessionFlag } from "./sessionFlags";

/** "3 h", "2 d": how late a queued step arrived. */
function late(seconds: number): string {
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

/** How a session's end reads: a stop record, no record for the idle time, or still open. */
export function sessionState(s: AgentSession, short = false): string {
  const state = s.state ?? (s.stopped ? "ended" : "open");
  if (state === "ended") return "ended";
  if (state === "idle") return short ? "ended (no end event)" : "Ended (no end event)";
  return short ? "open" : "still open";
}

function readOpen(): string | null {
  const m = /(?:^|&)session=([^&]+)/.exec(window.location.hash.replace(/^#/, ""));
  return m?.[1] ? decodeURIComponent(m[1]) : null;
}

/** Agent sessions from the hooks plugin (ADR-0026), as list and detail (ADR-0038 section 6):
 * the list on the left, newest first; the open session on the right with its Claude account
 * tier, tools, and steps in order. Metadata only: what was touched, never what was said. */
export function SessionsCard() {
  const list = useQuery({ queryKey: ["ai-sessions"], queryFn: () => api.aiSessions(7) });
  const accounts = useQuery({ queryKey: ["agent-accounts"], queryFn: () => api.agentAccounts(30) });
  const [open, setOpenState] = useState<string | null>(readOpen);
  const setOpen = (id: string | null) => {
    setOpenState(id);
    const url = `${window.location.pathname}${id ? `#session=${encodeURIComponent(id)}` : ""}`;
    window.history.replaceState(null, "", url);
  };
  const timeline = useQuery({
    queryKey: ["ai-session", open],
    queryFn: () => api.aiSession(open ?? ""),
    enabled: open !== null,
  });
  const [hideEmpty, setHideEmpty] = useState(true);
  const now = new Date().toISOString();
  const all = list.data ?? [];
  // Test or empty sessions (a start and nothing else) clutter the list (owner 2026-11-02).
  const shown = hideEmpty ? all.filter((r) => r.tool_calls > 0 || r.prompts > 0) : all;
  const hidden = all.length - shown.length;
  const account = (email: string | null) =>
    email ? accounts.data?.rows.find((a) => a.email === email.toLowerCase()) : undefined;
  // Filters (owner, 2026-11-03; D188): person, machine, tool, and has flags.
  const [person, setPerson] = useState("");
  const [machine, setMachine] = useState("");
  const [tool, setTool] = useState("");
  const [flagged, setFlagged] = useState(false);
  const flagsOf = (r: AgentSession) => sessionFlags(r, account);
  const rows = shown.filter(
    (r) =>
      (!person || r.person === person) &&
      (!machine || r.machine === machine) &&
      (!tool || r.tools.includes(tool)) &&
      (!flagged || flagsOf(r).length > 0),
  );
  const filtered = shown.length - rows.length;
  const current = rows.find((r) => r.session_id === open) ?? null;
  const options = (pick: (r: AgentSession) => (string | null)[]) =>
    [...new Set(shown.flatMap(pick).filter((v): v is string => !!v))].sort();
  return (
    <section
      aria-label="Agent sessions"
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-surface-head px-3 py-2">
        <SectionTitle>Sessions</SectionTitle>
        <span className="text-sm text-text-muted">
          Claude Code and Cowork sessions from the hooks plugin, last 7 days. Browser chat is not
          covered.
        </span>
        <label className="ml-auto flex items-center gap-1.5 text-sm text-text-secondary">
          <input
            type="checkbox"
            checked={hideEmpty}
            onChange={(e) => setHideEmpty(e.target.checked)}
          />
          Hide sessions with no tool calls or prompts
          {hideEmpty && hidden > 0 ? (
            <span className="tabular-nums text-text-muted">({hidden} hidden)</span>
          ) : null}
        </label>
      </div>
      {shown.length > 0 ? (
        <div
          role="group"
          aria-label="Filter sessions"
          className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2 text-sm"
        >
          <Pick label="Person" value={person} set={setPerson} values={options((r) => [r.person])} />
          <Pick
            label="Machine"
            value={machine}
            set={setMachine}
            values={options((r) => [r.machine])}
          />
          <Pick label="Tool" value={tool} set={setTool} values={options((r) => r.tools)} />
          <label className="flex items-center gap-1.5 text-text-secondary">
            <input
              type="checkbox"
              checked={flagged}
              onChange={(e) => setFlagged(e.target.checked)}
            />
            Has flags
          </label>
          {filtered > 0 ? (
            <span className="tabular-nums text-text-muted">
              {rows.length} of {shown.length} shown
            </span>
          ) : null}
        </div>
      ) : null}
      {list.error ? (
        <p role="alert" className="px-3 py-4 text-sm text-danger">
          {list.error instanceof ApiError ? list.error.message : "Could not load sessions"}
        </p>
      ) : rows.length === 0 && list.isSuccess ? (
        <p className="px-3 py-4 text-sm text-text-secondary">
          {filtered > 0
            ? "No sessions match these filters."
            : hidden > 0
              ? `No sessions with tool calls or prompts. ${hidden} empty ${hidden === 1 ? "session is" : "sessions are"} hidden.`
              : "No sessions yet. Download the Claude plugin from Settings > Claude plugins and install it."}
        </p>
      ) : (
        <div className="grid min-h-80 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <ul aria-label="Sessions" className="border-border lg:border-r">
            {rows.map((s) => {
              const on = open === s.session_id;
              return (
                <li key={s.session_id} className="border-b border-border last:border-0">
                  <button
                    type="button"
                    aria-current={on ? "true" : undefined}
                    onClick={() => setOpen(on ? null : s.session_id)}
                    className={cn(
                      "grid w-full grid-cols-[minmax(0,1fr)_auto] gap-x-3 px-3 py-2 text-left text-sm hover:bg-surface-head",
                      on && "bg-row-selected",
                    )}
                  >
                    <span className="truncate font-semibold">{s.person ?? "No user parsed"}</span>
                    <span className="text-text-muted" title={`${stamp(s.last)} UTC`}>
                      {since(s.last, now)}
                    </span>
                    <span className="truncate font-mono text-text-secondary">
                      {s.machine ?? ""}
                    </span>
                    <span className="tabular-nums text-text-secondary">
                      {sessionState(s, true)}, {duration(s.started, s.last)}
                    </span>
                    <span className="col-span-2 truncate tabular-nums text-text-secondary">
                      {count(s.prompts, "prompt")}, {count(s.tool_calls, "call")},{" "}
                      {count(s.files ?? 0, "file")}, {count(s.hosts.length, "web domain")}
                      {s.failed ? <span className="text-warn">, {s.failed} failed</span> : null}
                    </span>
                    {(s.top_tools ?? []).length > 0 || flagsOf(s).length > 0 ? (
                      <span className="col-span-2 flex flex-wrap items-center gap-1">
                        {(s.top_tools ?? []).length > 0 ? (
                          <span className="mr-1 truncate font-mono text-xs text-text-muted">
                            {(s.top_tools ?? []).join(", ")}
                          </span>
                        ) : null}
                        {flagsOf(s).map((f) => (
                          <FlagBadge key={f} flag={f} />
                        ))}
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
          <div className="min-w-0 border-t border-border px-3 py-2 lg:border-t-0">
            {!open ? (
              <p className="py-6 text-center text-sm text-text-secondary">
                Pick a session to see its account, tools, and steps in order.
              </p>
            ) : timeline.isLoading ? (
              <div aria-busy="true" className="h-40 animate-pulse" />
            ) : timeline.data ? (
              <Detail
                person={timeline.data.person}
                machine={timeline.data.machine}
                session={current}
                id={timeline.data.session_id}
                steps={timeline.data.steps}
                account={account(timeline.data.person)}
              />
            ) : null}
          </div>
        </div>
      )}
    </section>
  );
}

interface DetailProps {
  id: string;
  person: string | null;
  machine: string | null;
  session: AgentSession | null;
  steps: SessionStep[];
  account: AgentAccount | undefined;
}

function Detail({ id, person, machine, session, steps, account }: DetailProps) {
  const [around, setAround] = useState<SessionStep | null>(null);
  const late_ = steps.reduce((m, st) => Math.max(m, st.late_s ?? 0), 0);
  return (
    <div aria-label="Session detail" role="region">
      <PanelTitle>
        {person ? <EntityLink kind="user" value={person} tab="ai" /> : "No user parsed"}
        {machine ? (
          <span className="ml-2 font-mono font-normal">
            <EntityLink kind="host" value={machine} />
          </span>
        ) : null}
      </PanelTitle>
      <dl className="mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-0.5 text-sm">
        <dt className="text-text-secondary">Session</dt>
        <dd className="font-mono">{id}</dd>
        <dt className="text-text-secondary">Claude account</dt>
        <dd>
          {account ? (
            <>
              <TierBadge tier={account.tier} />{" "}
              <span className="text-text-secondary">{account.evidence}</span>
            </>
          ) : (
            <span className="text-text-secondary">
              {TIER_LABEL.not_checked}: no account reported
            </span>
          )}
        </dd>
        {session ? (
          <>
            <dt className="text-text-secondary">Started</dt>
            <dd>
              <When iso={session.started} />, {sessionState(session)}
            </dd>
            <dt className="text-text-secondary">Last seen</dt>
            <dd>
              <When iso={session.last} />
            </dd>
            <dt className="text-text-secondary">Calls</dt>
            <dd className="tabular-nums">
              {session.tool_calls} tool calls
              {session.failed ? `, ${session.failed} failed` : ""}, {session.prompts}{" "}
              {session.prompts === 1 ? "prompt" : "prompts"}
            </dd>
            <dt className="text-text-secondary">Tools and hosts</dt>
            <dd className="font-mono text-text-secondary">
              {[...session.tools, ...session.hosts].join(", ") || "None"}
            </dd>
          </>
        ) : null}
        {late_ ? (
          <>
            <dt className="text-text-secondary">Delivery</dt>
            <dd>Up to {late(late_)} late, from the plugin's offline queue</dd>
          </>
        ) : null}
      </dl>
      <SessionTurns steps={steps} around={around} onAround={setAround} />
      {around ? (
        <div className="mt-2">
          <AroundEvent eventId={around.event_id} at={around.time} />
        </div>
      ) : null}
    </div>
  );
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

const END: Record<Turn["end"], string> = {
  finished: "Finished",
  interrupted: "Interrupted: no turn end before the next prompt or the session end",
  open: "No turn end yet (still running, or interrupted)",
};

interface TurnsProps {
  steps: SessionStep[];
  around: SessionStep | null;
  onAround: (s: SessionStep | null) => void;
}

/** The timeline by turn (owner, 2026-11-03; D187): the prompt, the tool calls under it
 * each with its result, then how the turn ended. No "Turn end" rows; Around shows on
 * hover or focus of a row. */
function SessionTurns({ steps, around, onAround }: TurnsProps) {
  const g = groupTurns(steps);
  const aroundButton = (st: SessionStep) => (
    <button
      type="button"
      aria-pressed={around?.event_id === st.event_id}
      aria-label={`Around this step at ${new Date(st.time).toLocaleTimeString("en-US")}`}
      onClick={() => onAround(around?.event_id === st.event_id ? null : st)}
      className={cn(
        "text-xs text-accent-text hover:underline focus:opacity-100 group-hover:opacity-100",
        around?.event_id === st.event_id ? "opacity-100" : "opacity-0",
      )}
    >
      Around
    </button>
  );
  const row =
    "group grid grid-cols-[6.5rem_minmax(0,1fr)_auto_auto] items-baseline gap-x-3 py-0.5 text-sm";
  return (
    <ol aria-label="Session timeline" className="mt-2 flex flex-col gap-2">
      {g.started ? (
        <li className={row}>
          <StepTime iso={g.started.time} />
          <span className="text-text-secondary">Session started</span>
          <span />
          {aroundButton(g.started)}
        </li>
      ) : null}
      {g.turns.map((t, i) => (
        <li key={t.prompt?.event_id ?? `turn-${i}`} className="border-t border-border pt-1">
          <ol aria-label={`Turn ${i + 1}`} className="flex flex-col">
            {t.prompt ? (
              <li className={row}>
                <StepTime iso={t.prompt.time} />
                <span className="font-semibold">Prompt</span>
                <span className="text-text-muted tabular-nums">{size(t.prompt)}</span>
                {aroundButton(t.prompt)}
              </li>
            ) : null}
            {t.calls.map((c) => (
              <CallRow key={(c.call ?? c.result)!.event_id} c={c} row={row} button={aroundButton} />
            ))}
            <li className={cn(row, "text-text-secondary")}>
              {t.endedAt ? <StepTime iso={t.endedAt} /> : <span />}
              <span>
                {END[t.end]}
                {t.calls.length
                  ? `, ${t.calls.length} tool ${t.calls.length === 1 ? "call" : "calls"}`
                  : ""}
                {t.calls.some((c) => c.result?.event.endsWith("failure"))
                  ? `, ${t.calls.filter((c) => c.result?.event.endsWith("failure")).length} failed`
                  : ""}
              </span>
              <span />
              <span />
            </li>
          </ol>
        </li>
      ))}
      {g.ended ? (
        <li className={cn(row, "border-t border-border pt-1")}>
          <StepTime iso={g.ended.time} />
          <span className="text-text-secondary">Session ended</span>
          <span />
          {aroundButton(g.ended)}
        </li>
      ) : null}
    </ol>
  );
}

function CallRow({
  c,
  row,
  button,
}: {
  c: ToolCall;
  row: string;
  button: (s: SessionStep) => JSX.Element;
}) {
  const st = (c.call ?? c.result)!;
  const failed = c.result?.event.endsWith("failure") ?? false;
  const what = target(c.call ?? st) || (c.result ? target(c.result) : "");
  const sz = c.result ? size(c.result) : size(st);
  const lateBy = c.result?.late_s ?? st.late_s;
  return (
    <li className={row}>
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
      <span className="text-text-muted tabular-nums">
        {[sz, lateBy ? `delivered ${late(lateBy)} late` : ""].filter(Boolean).join(", ")}
      </span>
      {button(st)}
    </li>
  );
}

function count(n: number, word: string): string {
  return `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;
}

function FlagBadge({ flag }: { flag: SessionFlag }) {
  return (
    <span className="rounded-badge bg-sev-medium-bg px-1.5 py-px text-xs text-sev-medium-text">
      {FLAG_LABEL[flag]}
    </span>
  );
}

interface PickProps {
  label: string;
  value: string;
  set: (v: string) => void;
  values: string[];
}

function Pick({ label, value, set, values }: PickProps) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => set(e.target.value)}
      className="h-7 max-w-48 rounded border border-border-strong bg-surface px-1.5"
    >
      <option value="">Any {label.toLowerCase()}</option>
      {values.map((v) => (
        <option key={v} value={v}>
          {v}
        </option>
      ))}
    </select>
  );
}
