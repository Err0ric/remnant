import { EntityLink } from "@/components/EntityLink";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, type AgentAccount, type AgentSession, type SessionStep } from "@/lib/api";
import { cn } from "@/lib/cn";
import { TIER_LABEL, TierBadge } from "./AccountsCard";
import { since, stamp } from "@/features/overview/time";

const ROLE: Record<string, string> = {
  session: "Session",
  user: "Prompt",
  tool_call: "Tool call",
  tool_result: "Result",
  turn: "Turn",
};

const EVENT: Record<string, string> = {
  session_start: "Started",
  user_prompt_submit: "Prompt",
  pre_tool_use: "Calls",
  post_tool_use: "Returned",
  post_tool_use_failure: "Failed",
  stop: "Turn end",
  session_end: "Ended",
};

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
  const now = new Date().toISOString();
  const rows = list.data ?? [];
  const current = rows.find((r) => r.session_id === open) ?? null;
  const account = (email: string | null) =>
    email ? accounts.data?.rows.find((a) => a.email === email.toLowerCase()) : undefined;
  return (
    <section
      aria-label="Agent sessions"
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-surface-head px-3 py-2">
        <h2 className="text-base font-semibold">Sessions</h2>
        <span className="text-sm text-text-muted">
          Claude Code and Cowork sessions from the hooks plugin, last 7 days. Browser chat is not
          covered.
        </span>
      </div>
      {list.error ? (
        <p role="alert" className="px-3 py-4 text-sm text-danger">
          {list.error instanceof ApiError ? list.error.message : "Could not load sessions"}
        </p>
      ) : rows.length === 0 && list.isSuccess ? (
        <p className="px-3 py-4 text-sm text-text-secondary">
          No sessions yet. Download the Claude plugin from an OTLP source on Sources and publish it
          to your organization.
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
                      {s.stopped ? "ended" : "open"}, {s.tool_calls} calls
                      {s.failed ? <span className="text-warn">, {s.failed} failed</span> : null}
                    </span>
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
  const late_ = steps.reduce((m, st) => Math.max(m, st.late_s ?? 0), 0);
  return (
    <div aria-label="Session detail" role="region">
      <h3 className="text-sm font-semibold">
        {person ?? "No user parsed"}
        {machine ? (
          <span className="ml-2 font-mono font-normal">
            <EntityLink kind="host" value={machine} />
          </span>
        ) : null}
      </h3>
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
              {stamp(session.started)} UTC, {session.stopped ? "ended" : "still open"}
            </dd>
            <dt className="text-text-secondary">Calls</dt>
            <dd className="tabular-nums">
              {session.tool_calls} tool calls
              {session.failed ? `, ${session.failed} failed` : ""}, {session.prompts} prompts
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
      <ol aria-label="Session timeline" className="mt-2 flex flex-col">
        {steps.map((st) => (
          <li
            key={st.event_id}
            className="grid grid-cols-[5rem_5.5rem_minmax(0,1fr)_auto] items-baseline gap-x-3 border-b border-border py-1 text-sm last:border-0"
          >
            <time
              dateTime={st.time}
              title={`${stamp(st.time)} UTC`}
              className="font-mono text-text-muted tabular-nums"
            >
              {st.time.slice(11, 19)}
            </time>
            <span className="text-text-secondary">{ROLE[st.role ?? ""] ?? st.role}</span>
            <span
              className={cn(
                "min-w-0 truncate",
                st.event === "post_tool_use_failure" && "text-warn",
              )}
              title={target(st)}
            >
              {EVENT[st.event] ?? st.event}
              {st.tool && !st.mcp_server ? <span className="font-mono"> {st.tool}</span> : null}
              {target(st) ? (
                <span className="font-mono text-text-secondary"> {target(st)}</span>
              ) : null}
            </span>
            <span className="text-text-muted tabular-nums">
              {size(st)}
              {st.late_s ? (
                <span title="Sent from the plugin's queue after the computer was offline">
                  {size(st) ? ", " : ""}delivered {late(st.late_s)} late
                </span>
              ) : null}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
