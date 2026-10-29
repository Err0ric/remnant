import { EntityLink } from "@/components/EntityLink";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, type SessionStep } from "@/lib/api";
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

/** Agent sessions from the hooks plugin (ADR-0026): newest first; open one to see it in
 * order, start to stop. Metadata only: what was touched, never what was said. */
export function SessionsCard() {
  const list = useQuery({ queryKey: ["ai-sessions"], queryFn: () => api.aiSessions(7) });
  const [open, setOpen] = useState<string | null>(null);
  const timeline = useQuery({
    queryKey: ["ai-session", open],
    queryFn: () => api.aiSession(open ?? ""),
    enabled: open !== null,
  });
  const now = new Date().toISOString();
  const rows = list.data ?? [];
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
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-secondary">
                <th className="px-3 py-2 font-semibold">Person</th>
                <th className="px-3 py-2 font-semibold">Machine</th>
                <th className="px-3 py-2 font-semibold">Last activity</th>
                <th className="px-3 py-2 text-right font-semibold">Prompts</th>
                <th className="px-3 py-2 text-right font-semibold">Tool calls</th>
                <th className="px-3 py-2 font-semibold">Tools and hosts</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr
                  key={s.session_id}
                  className={`border-b border-border last:border-0 ${open === s.session_id ? "bg-surface-expand" : ""}`}
                >
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      aria-expanded={open === s.session_id}
                      onClick={() => setOpen(open === s.session_id ? null : s.session_id)}
                      className="text-left text-accent-text hover:underline"
                    >
                      {s.person ?? "No user parsed"}
                    </button>
                  </td>
                  <td className="px-3 py-2 font-mono">
                    {s.machine ? <EntityLink kind="host" value={s.machine} /> : ""}
                  </td>
                  <td className="px-3 py-2" title={`${stamp(s.last)} UTC`}>
                    {since(s.last, now)}
                    {s.stopped ? "" : ", still open"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.prompts}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{s.tool_calls}</td>
                  <td className="px-3 py-2 font-mono text-text-secondary">
                    {[...s.tools, ...s.hosts].join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && timeline.data ? (
        <div className="border-t border-border px-3 py-2">
          <h3 className="mb-1 text-sm font-semibold">
            Session <span className="font-mono">{timeline.data.session_id}</span>
          </h3>
          <ol aria-label="Session timeline" className="flex flex-col">
            {timeline.data.steps.map((st) => (
              <li
                key={st.event_id}
                className="grid grid-cols-[6.5rem_6rem_minmax(0,1fr)_auto] items-baseline gap-x-3 border-b border-border py-1 text-sm last:border-0"
              >
                <time
                  dateTime={st.time}
                  title={`${stamp(st.time)} UTC`}
                  className="font-mono text-text-muted tabular-nums"
                >
                  {st.time.slice(11, 19)}
                </time>
                <span className="text-text-secondary">{ROLE[st.role ?? ""] ?? st.role}</span>
                <span className="min-w-0 truncate" title={target(st)}>
                  {EVENT[st.event] ?? st.event}
                  {st.tool && !st.mcp_server ? <span className="font-mono"> {st.tool}</span> : null}
                  {target(st) ? (
                    <span className="font-mono text-text-secondary"> {target(st)}</span>
                  ) : null}
                </span>
                <span className="text-text-muted tabular-nums">{size(st)}</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </section>
  );
}
