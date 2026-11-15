import { lastDays } from "@/lib/timeWindow";
import { EmptyState } from "@/components/EmptyState";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, type AgentSession } from "@/lib/api";
import { cn } from "@/lib/cn";
import { FilterBar } from "@/components/FilterBar";
import { useFilters } from "@/lib/filters";
import { fragmentValues, setFragment, useSection } from "@/lib/route";
import { since, stamp } from "@/features/overview/time";
import { Card } from "@/components/Card";
import { StateNotice } from "@/components/StateNotice";
import { NAMES_HIDDEN } from "@/features/alerts/kinds";
import { duration, FLAG_LABEL, sessionFlags, type SessionFlag } from "./sessionFlags";
import { SessionDetail } from "./SessionDetail";

/** How a session's end reads: a stop record, no record for the idle time, or still open. */
export function sessionState(s: AgentSession, short = false): string {
  const state = s.state ?? (s.stopped ? "ended" : "open");
  if (state === "ended") return "ended";
  if (state === "idle") return short ? "ended (no end event)" : "Ended (no end event)";
  return short ? "open" : "still open";
}

const FILTER_DEFAULTS = { person: "", machine: "", tool: "", flags: "" };

/** Agent sessions from the hooks plugin (ADR-0026), as list and detail (DESIGN.md 6.0 and
 * 6.2b): the list on the left (5 parts), newest first, with its filters; the open session
 * in a sticky pane on the right (7 parts). On a narrow window the open session takes the
 * page, with Back. Metadata only: what was touched, never what was said. */
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
    // Another session starts on its own defaults (Execution, All).
    if (id !== open) {
      next.delete("view");
      next.delete("show");
    }
    setFragment(next.toString(), true);
  };
  const back = () => {
    const was = open;
    setOpen(null);
    // Back on a narrow window: focus returns to the session's row in the list.
    requestAnimationFrame(() =>
      [...document.querySelectorAll<HTMLElement>("[data-session]")]
        .find((el) => el.dataset.session === was)
        ?.focus(),
    );
  };
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
    <div
      className={cn(
        "grid min-w-0 items-start gap-3",
        (open || rows.length > 0) && "lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]",
      )}
    >
      <Card
        className={open ? "max-lg:hidden" : undefined}
        title="Sessions"
        label="Agent sessions"
        note={`${lastDays(days)}, from the hooks plugin`}
        about="Claude Code and Cowork sessions from the hooks plugin. Browser chat is not covered."
      >
        {masked ? (
          <div className="border-b border-border p-2">
            <StateNotice>{NAMES_HIDDEN}</StateNotice>
          </div>
        ) : null}
        {all.length > 0 ? (
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
              columns={
                <label className="flex items-center gap-1.5 whitespace-nowrap text-sm text-text-secondary">
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
          <ul aria-label="Sessions">
            {rows.map((s) => {
              const on = open === s.session_id;
              return (
                <li key={s.session_id} className="border-b border-border last:border-0">
                  <button
                    type="button"
                    data-session={s.session_id}
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
        )}
      </Card>
      {open || rows.length > 0 ? (
        <section
          aria-label="The open session"
          className={cn(
            "min-w-0 rounded-card border border-border bg-surface lg:sticky lg:top-12",
            !open && "max-lg:hidden",
          )}
        >
          {open ? (
            <SessionDetail
              key={open}
              id={open}
              newMcp={all.find((r) => r.session_id === open)?.new_mcp}
              account={account}
              onBack={back}
            />
          ) : (
            <EmptyState kind="default-empty" title="Pick a session." />
          )}
        </section>
      ) : null}
    </div>
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
