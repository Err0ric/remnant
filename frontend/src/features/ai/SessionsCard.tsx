import { lastDays } from "@/lib/timeWindow";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/Skeleton";
import { EntityLink } from "@/components/EntityLink";
import { When } from "@/components/When";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { AroundEvent } from "@/features/search/AroundEvent";
import { ApiError, api, type AgentAccount, type AgentSession, type SessionStep } from "@/lib/api";
import { cn } from "@/lib/cn";
import { FilterBar } from "@/components/FilterBar";
import { useFilters } from "@/lib/filters";
import { fragmentValues, setFragment, useSection } from "@/lib/route";
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

const FILTER_DEFAULTS = { person: "", machine: "", tool: "", flags: "" };

/** Agent sessions from the hooks plugin (ADR-0026), as list and detail (ADR-0038 section 6):
 * the list on the left, newest first; the open session on the right with its Claude account
 * tier, tools, and steps in order. Metadata only: what was touched, never what was said. */
interface SessionsCardProps {
  /** Whole days back from now, from the page's time choice (as the strip above counts). */
  days?: number;
}

export function SessionsCard({ days = 7 }: SessionsCardProps) {
  const list = useQuery({
    queryKey: ["ai-sessions", days],
    queryFn: () => api.aiSessions(days),
  });
  const accounts = useQuery({ queryKey: ["agent-accounts"], queryFn: () => api.agentAccounts(30) });
  // The open session is the one in the address, so Back and a sent link agree with the pane.
  const open = fragmentValues(useSection()).get("session");
  const setOpen = (id: string | null) => {
    // Beside the filters in the fragment, which stay.
    const next = fragmentValues(window.location.hash.replace(/^#/, ""));
    if (id) next.set("session", id);
    else next.delete("session");
    setFragment(next.toString(), true);
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
  // Without View people in AI usage (D242) the server sends machines, not accounts: no
  // lookup, so a machine is never matched to another account's tier.
  const masked = all.some((r) => r.masked) || accounts.data?.masked === true;
  const account = (email: string | null) =>
    email && !masked ? accounts.data?.rows.find((a) => a.email === email.toLowerCase()) : undefined;
  // Filters (owner, 2026-11-03; D188): person, machine, tool, and has flags.
  // In the address (DESIGN.md 6.0), so a filtered list can be sent or bookmarked.
  const filters = useFilters(FILTER_DEFAULTS, { flags: ["", "flagged"] });
  // Without names, a person in the address filters nothing (and is not offered).
  const person = masked ? "" : filters.values.person;
  const { machine, tool } = filters.values;
  const flagged = filters.values.flags === "flagged";
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
  const facet = (
    name: string,
    key: "person" | "machine" | "tool",
    pick: (r: AgentSession) => (string | null)[],
  ) => ({
    name,
    value: key === "person" ? person : filters.values[key],
    // A value in the address that no listed session has stays selectable, so it shows.
    options: [
      { id: "", label: "Any" },
      ...[...new Set([...options(pick), ...(filters.values[key] ? [filters.values[key]] : [])])]
        .sort()
        .map((v) => ({ id: v, label: v })),
    ],
    onChange: (id: string) => filters.set(key, id),
  });
  return (
    <section
      aria-label="Agent sessions"
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-surface-head px-3 py-2">
        <SectionTitle>Sessions</SectionTitle>
        <span className="text-sm text-text-muted">
          {lastDays(days)}. Claude Code and Cowork sessions from the hooks plugin. Browser chat is
          not covered.
          {masked
            ? " Names are hidden. An admin can turn on View people in AI usage for you."
            : null}
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
        <div className="border-b border-border px-3 py-1">
          <FilterBar
            label="Filter sessions"
            facets={[
              ...(masked ? [] : [facet("Person", "person", (r) => [r.person])]),
              facet("Machine", "machine", (r) => [r.machine]),
              facet("Tool", "tool", (r) => r.tools),
              {
                name: "Flags",
                value: filters.values.flags,
                options: [
                  { id: "", label: "Any" },
                  { id: "flagged", label: "Flagged" },
                ],
                onChange: (id) => filters.set("flags", id),
              },
            ]}
            count={
              filtered > 0
                ? `${rows.length} of ${shown.length} ${shown.length === 1 ? "session" : "sessions"}`
                : `${shown.length} ${shown.length === 1 ? "session" : "sessions"}`
            }
            onReset={filters.reset}
            isDefault={!machine && !tool && !flagged && !person}
          />
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
              <EmptyState kind="default-empty" title="Pick a session." />
            ) : timeline.isLoading ? (
              <Skeleton label="the session" rows={4} className="rounded-none border-0" />
            ) : timeline.data ? (
              <Detail
                person={timeline.data.person}
                machine={timeline.data.machine}
                session={current}
                id={timeline.data.session_id}
                steps={timeline.data.steps}
                account={account(timeline.data.person)}
                masked={timeline.data.masked === true}
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
  /** `person` is the machine (or "Hidden"), D242: plain text, no person link. */
  masked: boolean;
}

function Detail({ id, person, machine, session, steps, account, masked }: DetailProps) {
  const [around, setAround] = useState<SessionStep | null>(null);
  const late_ = steps.reduce((m, st) => Math.max(m, st.late_s ?? 0), 0);
  return (
    <div aria-label="Session detail" role="region">
      <PanelTitle>
        {person && masked ? (
          person
        ) : person ? (
          <EntityLink kind="user" value={person} tab="ai" />
        ) : (
          "No user parsed"
        )}
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
          {masked && person ? (
            <span className="text-text-secondary">Hidden</span>
          ) : account ? (
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
    <span className="rounded-badge border border-warn px-1.5 py-px text-xs text-warn">
      {FLAG_LABEL[flag]}
    </span>
  );
}
