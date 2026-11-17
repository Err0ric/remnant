import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { EntityLink } from "@/components/EntityLink";
import { InlineError } from "@/components/InlineError";
import { KpiTile } from "@/components/KpiTile";
import { Segmented } from "@/components/FilterBar";
import { Skeleton } from "@/components/Skeleton";
import { StateNotice } from "@/components/StateNotice";
import { When } from "@/components/When";
import { AroundEvent } from "@/features/search/AroundEvent";
import { api, type AgentAccount, type SessionStep, type SessionSummary } from "@/lib/api";
import { openDrill } from "@/lib/drill";
import { fragmentValues, setFragment, useSection } from "@/lib/route";
import { TIER_LABEL, TierBadge } from "./AccountsCard";
import { SessionBar } from "./SessionBar";
import { ConversationSteps, ExecutionSteps, late, shownSteps } from "./SessionSteps";
import { duration, failedOrBlocked, FLAG_LABEL, sessionFlags } from "./sessionFlags";
import { flaggedSteps } from "./sessionTurns";

export const NOT_COLLECTED = "Content is not collected. Sizes and names only.";

/** One fragment value beside the others; the default is left out of the address. */
function useFragmentChoice<T extends string>(key: string, fallback: T, allowed: readonly T[]) {
  const raw = fragmentValues(useSection()).get(key);
  const value = allowed.includes(raw as T) ? (raw as T) : fallback;
  const set = (v: T) => {
    const next = fragmentValues(window.location.hash.replace(/^#/, ""));
    if (v === fallback) next.delete(key);
    else next.set(key, v);
    setFragment(next.toString(), true);
  };
  return [value, set] as const;
}

const n = (v: number) => v.toLocaleString();

interface SessionDetailProps {
  id: string;
  /** The MCP servers new in this session as the list's row counts them (over the list's
   * days), so the Flags tile and flagged steps agree with the row; the summary's own (over
   * its 30 days) when the session is not in the list. */
  newMcp?: string[];
  account: (email: string | null) => AgentAccount | undefined;
  onBack: () => void;
}

/** The open session (BACKLOG P1, the mock in docs/proposals): header, the numbers for the
 * whole session from the server, then its steps as Execution or Conversation. Metadata
 * only; no way to open content. */
export function SessionDetail({ id, newMcp, account, onBack }: SessionDetailProps) {
  // Both reads use the server's 30 days, never the list's window: an open session (or a
  // sent link) never disappears or shrinks because the page's time is shorter.
  const summary = useQuery({
    queryKey: ["ai-session-summary", id],
    queryFn: () => api.aiSessionSummary(id),
  });
  const timeline = useQuery({
    queryKey: ["ai-session", id],
    queryFn: () => api.aiSession(id),
  });
  const [view, setView] = useFragmentChoice("view", "execution", ["execution", "conversation"]);
  const [show, setShow] = useFragmentChoice("show", "all", ["all", "flagged"]);
  const [around, setAround] = useState<SessionStep | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  // On a narrow window the pane replaces the list: take focus to its heading.
  useEffect(() => {
    if (window.matchMedia?.("(max-width: 1023px)").matches) heading.current?.focus();
  }, [id]);
  const s = summary.data ? { ...summary.data, new_mcp: newMcp ?? summary.data.new_mcp } : undefined;
  const t = timeline.data;
  const machine = s?.machine ?? t?.machine ?? null;
  const steps = t?.steps ?? [];
  const flagged = s
    ? flaggedSteps(steps, s.state === "open", s.new_mcp, s.steps_cut)
    : new Set<string>();
  const stepsProps = {
    steps,
    flagged,
    flaggedOnly: show === "flagged",
    around,
    onAround: setAround,
  };
  // A segment of the bar opens its step in the view below: scrolled to, focused, and
  // marked for a moment.
  const pane = useRef<HTMLDivElement>(null);
  const openStep = (eventId: string) => {
    const row = [...(pane.current?.querySelectorAll<HTMLElement>("[data-steps]") ?? [])].find(
      (el) => el.dataset.steps?.split(" ").includes(eventId),
    );
    if (!row) return;
    row.scrollIntoView?.({ block: "center" });
    row.focus({ preventScroll: true });
    row.classList.add("bg-row-selected");
    window.setTimeout(() => row.classList.remove("bg-row-selected"), 1500);
  };
  const lateMax = steps.reduce((m, st) => Math.max(m, st.late_s ?? 0), 0);
  return (
    <div ref={pane} aria-label="Session detail" role="region" className="grid gap-3 px-3 py-2">
      <button
        type="button"
        onClick={onBack}
        className="justify-self-start text-sm text-accent-text hover:underline lg:hidden"
      >
        Back to sessions
      </button>
      <header className="grid gap-1">
        <h2 ref={heading} tabIndex={-1} className="text-md font-semibold outline-none">
          Session on {machine ? <EntityLink kind="host" value={machine} /> : "an unknown machine"}
        </h2>
        {s ? (
          <Who s={s} account={account} />
        ) : t ? (
          // The numbers did not load: the person from the steps answer, masked alike.
          <p className="text-sm">
            {t.person && !t.masked ? (
              <EntityLink kind="user" value={t.person} tab="ai" />
            ) : (
              (t.person ?? "No user parsed")
            )}
          </p>
        ) : null}
        <p className="font-mono text-xs text-text-muted">{id}</p>
        {lateMax ? (
          <p className="text-sm text-text-secondary">
            Some steps arrived up to {late(lateMax)} late, from the plugin's offline queue.
          </p>
        ) : null}
      </header>
      <StateNotice>{NOT_COLLECTED}</StateNotice>
      {summary.error ? (
        <InlineError
          what="This session's numbers"
          error={summary.error}
          onRetry={() => void summary.refetch()}
          retrying={summary.isFetching}
        />
      ) : null}
      <Kpis
        s={s}
        loading={summary.isLoading}
        failed={summary.error ? () => void summary.refetch() : undefined}
        account={account}
      />
      {t ? (
        <SessionBar
          steps={steps}
          summary={s}
          // Without the summary the flagged steps are not known: the bar then claims
          // nothing about flags (the list below says they could not be worked out).
          flagged={show === "flagged" && s ? flagged : null}
          shown={shownSteps(steps, view, flagged, show === "flagged")}
          onPick={openStep}
        />
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="flex items-center gap-2">
          <span className="text-text-secondary">View</span>
          <Segmented
            label="View"
            value={view}
            onChange={setView}
            options={[
              { id: "execution", label: "Execution" },
              { id: "conversation", label: "Conversation" },
            ]}
          />
        </span>
        <span className="flex items-center gap-2">
          <span className="text-text-secondary">Show</span>
          <Segmented
            label="Show"
            value={show}
            onChange={setShow}
            options={[
              { id: "all", label: "All" },
              { id: "flagged", label: "Flagged only" },
            ]}
          />
        </span>
      </div>
      {s?.steps_cut && t ? (
        <p className="text-sm text-text-secondary">
          Showing the first {n(steps.length)} of {n(s.steps)} steps. The numbers above count them
          all.
        </p>
      ) : null}
      {timeline.isLoading ? (
        <Skeleton label="the steps" rows={4} className="rounded-none border-0" />
      ) : timeline.error ? (
        <InlineError
          what="The steps"
          error={timeline.error}
          onRetry={() => void timeline.refetch()}
          retrying={timeline.isFetching}
        />
      ) : show === "flagged" && summary.isLoading ? (
        <Skeleton label="the flagged steps" rows={2} className="rounded-none border-0" />
      ) : show === "flagged" && !s ? (
        // Which steps are flagged needs the session's numbers (its state, new MCP servers).
        <EmptyState
          kind="filtered"
          title="Flagged steps could not be worked out: this session's numbers did not load."
          action={{ label: "Retry", onClick: () => void summary.refetch() }}
        />
      ) : show === "flagged" && s && flagged.size === 0 ? (
        s.steps_cut ? (
          <EmptyState
            kind="filtered"
            title={`None of the first ${n(steps.length)} steps is flagged.`}
            detail={`The whole session has ${n(failedOrBlocked(s))} failed or blocked ${failedOrBlocked(s) === 1 ? "call" : "calls"}, past the steps shown.`}
            action={{ label: "Show all", onClick: () => setShow("all") }}
          />
        ) : (
          <EmptyState
            kind="filtered"
            title="No flagged steps in this session."
            action={{ label: "Show all", onClick: () => setShow("all") }}
          />
        )
      ) : view === "conversation" ? (
        <ConversationSteps {...stepsProps} />
      ) : (
        <ExecutionSteps {...stepsProps} />
      )}
      {around ? <AroundEvent eventId={around.event_id} at={around.time} /> : null}
      {s?.sql ? (
        <footer className="border-t border-border pt-2">
          <button
            type="button"
            onClick={() =>
              openDrill({
                sql: s.sql,
                // A minute either side, so the first and last records are inside.
                from: new Date(Date.parse(s.started) - 60_000).toISOString(),
                to: new Date(Date.parse(s.last) + 60_000).toISOString(),
                origin: `Agents > Session on ${machine ?? "an unknown machine"}`,
              })
            }
            className="text-sm text-accent-text hover:underline"
          >
            Show events in Logs
          </button>
        </footer>
      ) : null}
    </div>
  );
}

/** Person (the machine when names are hidden, D242), the account's tier, start and length. */
function Who({ s, account }: { s: SessionSummary; account: SessionDetailProps["account"] }) {
  const acct = s.masked ? undefined : account(s.account ?? s.person);
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      {s.person && !s.masked ? (
        <EntityLink kind="user" value={s.person} tab="ai" />
      ) : (
        <span>{s.person ?? "No user parsed"}</span>
      )}
      {s.masked ? (
        <span className="text-text-secondary">Claude account hidden</span>
      ) : acct ? (
        <TierBadge tier={acct.tier} />
      ) : (
        <span className="text-text-secondary">{TIER_LABEL.not_checked}: no account reported</span>
      )}
      <span className="text-text-secondary">
        <When iso={s.started} />, {duration(s.started, s.last)}
        {s.state === "open" ? ", still open" : s.state === "idle" ? ", ended (no end event)" : ""}
      </span>
    </p>
  );
}

interface KpisProps {
  s: SessionSummary | undefined;
  loading: boolean;
  failed?: () => void;
  account: SessionDetailProps["account"];
}

/** The KPI row (D255 tiles in one strip): requests, tool calls, tokens, files, flags. */
function Kpis({ s, loading, failed, account }: KpisProps) {
  const tile = { loading, failed };
  const muted = (v: number) => (v === 0 ? "muted" : "text");
  const bad = s ? failedOrBlocked(s) : 0;
  const flags = s ? sessionFlags(s, account) : [];
  const metered = s && s.tokens_in !== null && s.tokens_out !== null;
  return (
    <div
      aria-label="This session in numbers"
      role="group"
      className="grid grid-cols-2 gap-px overflow-hidden rounded-card border border-border bg-border sm:grid-cols-5 [&>:last-child]:max-sm:col-span-2"
    >
      <KpiTile
        {...tile}
        label="Requests"
        value={s ? n(s.prompts) : ""}
        tone={muted(s?.prompts ?? 0)}
      />
      <KpiTile
        {...tile}
        label="Tool calls"
        value={s ? n(s.tool_calls) : ""}
        tone={muted(s?.tool_calls ?? 0)}
        context={bad ? `${n(bad)} failed or blocked` : undefined}
      />
      <KpiTile
        {...tile}
        label="Tokens"
        about="From Claude Code telemetry for this session. Input counts cache tokens too."
        value={
          metered ? (
            n(s.tokens_in! + s.tokens_out!)
          ) : (
            // Words, not a number: one line in the body size on the number's line, so the
            // tile keeps its height and nothing wraps in a narrow pane (fix list S2).
            <span className="whitespace-nowrap text-md font-normal">Not reported</span>
          )
        }
        tone={metered && s.tokens_in! + s.tokens_out! > 0 ? "text" : "muted"}
        context={metered ? `In ${n(s.tokens_in!)}, out ${n(s.tokens_out!)}` : undefined}
      />
      <KpiTile
        {...tile}
        label="Files"
        about="Distinct paths read or written. Outside the folder: written outside the session's working folder."
        value={s ? n(s.files) : ""}
        tone={muted(s?.files ?? 0)}
        context={s?.files_outside ? `${n(s.files_outside)} outside the folder` : undefined}
      />
      <KpiTile
        {...tile}
        label="Flags"
        value={n(flags.length)}
        tone={flags.length ? "warn" : "muted"}
        context={flags.length ? flags.map((f) => FLAG_LABEL[f]).join(", ") : undefined}
      />
    </div>
  );
}
