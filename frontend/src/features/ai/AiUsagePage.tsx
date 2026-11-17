import { ChevronRight } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import {
  attentionItems,
  count,
  NeedsAttention,
  useOpenAlertsItem,
} from "@/features/dashboard/NeedsAttention";
import { EntityLink, EntityList } from "@/components/EntityLink";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Skeleton } from "@/components/Skeleton";
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { PeoplePending } from "@/components/PeoplePending";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { PageHeader } from "@/components/shell/PageHeader";
import {
  ApiError,
  api,
  type AiGone,
  type AiPerson,
  type AiServiceUse,
  type AiStatus,
  type DataLevel,
} from "@/lib/api";
import { FilterBar } from "@/components/FilterBar";
import { usePageTime } from "@/lib/timeChoice";
import { fragmentValues, navigate, pathFor, useSection, useSectionTab } from "@/lib/route";
import { When } from "@/components/When";
import { AgentsCard } from "./AgentsCard";
import { SessionsCard } from "./SessionsCard";
import { AccountsCard } from "./AccountsCard";
import { windowOf } from "@/lib/timeWindow";
import { agentWindow } from "./agentWindow";
import { AgentsKpis, ToolRows, useAgentsOverview, useBuiltInCount } from "./AgentsOverview";
import { InventoryCard, type InventoryExport } from "./InventoryCard";
import { useAiInventoryCounts } from "./review";
import { StatusBadge, StatusPicker } from "./StatusBadge";
import { Card as SharedCard } from "@/components/Card";
import { StateNotice } from "@/components/StateNotice";
import { NAMES_HIDDEN } from "@/features/alerts/kinds";
import { Select } from "@/components/forms/Select";

type Tab = "services" | "sessions" | "mcp" | "accounts" | "people" | "inventory";
const KIND: Record<string, string> = {
  chat: "Chat",
  api: "API",
  coding: "Coding",
  agent_platform: "Agent builder",
  mcp_registry: "MCP registry",
  image: "Image and voice",
  meetings: "Meetings",
  writing: "Writing",
  non_usage: "Not AI use",
};

const LEVELS: DataLevel[] = ["public", "internal", "confidential"];
const LEVEL_LABEL: Record<DataLevel, string> = {
  public: "Public",
  internal: "Internal",
  confidential: "Confidential",
};

/** In the viewer's time zone (owner, 2026-10-31). */
function when(iso: string | null): string {
  return iso
    ? new Date(iso).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : "·";
}

/** How a person was seen reaching Claude (owner 2026-11-02). */
const SEEN: Record<"plugin" | "network" | "both", string> = {
  plugin: "Plugin",
  network: "Network",
  both: "Both",
};

function seenTitle(p: AiPerson): string {
  const via = (p.via ?? []).join(" and ");
  if (p.seen_through === "network")
    return "DNS, firewall, or proxy logs only: no telemetry or hooks record";
  if (p.seen_through === "both") return `The ${via || "plugin"} and the network`;
  return `The ${via || "plugin"} only: not seen on the network`;
}

/** On the Claude service row: who the network saw, who the plugin saw, and the gap. */
function SeenSummary({ seen }: { seen: Partial<Record<"both" | "plugin" | "network", number>> }) {
  return (
    <div className="text-text-secondary tabular-nums">
      People: {seen.network ?? 0} seen only on the network, {seen.plugin ?? 0} only by the Claude
      Code plugin, {seen.both ?? 0} by both
    </div>
  );
}

const TH = "px-3 py-2 text-left";
const TD = "px-3 py-2 align-top";

interface AiUsagePageProps {
  isAdmin: boolean;
  /** Admins and analysts export the inventory (ADR-0038 row 22). */
  canExport?: boolean;
  /** AI usage (services, people, review) or Agents (sessions, MCP servers); ADR-0038. */
  area?: "ai" | "agents";
}

const BUILT_IN = "\u0000built-in";

/** "Aug 19": a day of the window Agents read. */
const day = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

const say = (v: number, one: string, many: string) =>
  `${v.toLocaleString()} ${v === 1 ? one : many}`;

interface ToolsToggleProps {
  /** "Tools of Built-in", or "Calls and failures of github": what the row opens to. */
  label: string;
  open: boolean;
  onToggle: () => void;
}

/** Opens a row of MCP servers to its tools (they were the Tools tab). */
function ToolsToggle({ label, open, onToggle }: ToolsToggleProps) {
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-label={label}
      onClick={onToggle}
      className="flex h-6 w-6 items-center justify-center rounded text-text-secondary hover:bg-surface-head hover:text-text"
    >
      <ChevronRight size={14} aria-hidden className={open ? "rotate-90" : ""} />
    </button>
  );
}

/** AI usage (ADR-0015 row 8): services, agents and MCP servers, and Claude usage. */
export function AiUsagePage({ isAdmin, canExport = false, area = "ai" }: AiUsagePageProps) {
  const client = useQueryClient();
  // The page's one time control, in the address (ADR-0052 section 3.7).
  const time = usePageTime("7d");
  // The service whose review and allowed data are open under its row (list-detail).
  const [reviewing, setReviewing] = useState<string | null>(null);
  const tabs: Tab[] =
    area === "agents" ? ["sessions", "mcp", "accounts"] : ["services", "people", "inventory"];
  const [tab] = useSectionTab<Tab>(tabs);
  // The whole AI usage answer is the page's heaviest read (about 3.4 s of server CPU on 30
  // days of a busy install), and it held up the Agents tables beside it (fix list item 15):
  // on Agents only the MCP servers tab asks for it; Sessions and Accounts read their own.
  // Agents: one window for every number on the page (PR 639 review), the window the
  // overview read: the last 90 days of the time chosen, on the server's clock.
  const agentWin = useMemo(() => agentWindow(time), [time]);
  const agentsQ = useAgentsOverview(agentWin, area === "agents");
  const agents = agentsQ.data;
  const read = agents ? { start: agents.read_start, end: agents.read_end } : null;
  // The MCP servers table reads the same span as the overview. When the server will not
  // clamp the choice (every preset, any Custom of 90 days or less) that is the choice:
  // read at once, beside the overview. Only when it will clamp, the table waits for the
  // window the overview read and keeps its rows while that window moves (PR 639 review).
  const clamps = area === "agents" && agentWin.clamps;
  const wantUsage =
    area === "ai" || (tab === "mcp" && (!clamps || read !== null || agentsQ.isError));
  const usage = useQuery({
    enabled: wantUsage,
    // Keyed by the time chosen, never by the overview's moving window: the table is read
    // again only when the overview's MCP counts say it is out of date (below).
    queryKey: area === "agents" ? ["ai-usage", "agents", ...time.key] : ["ai-usage", ...time.key],
    queryFn: () => {
      const b = time.bounds();
      // This endpoint reads its bounds to the minute (it caches by them), and its end is
      // inclusive: the start of the next minute keeps the minute Custom's end names.
      const end = b.end
        ? new Date(Math.ceil(Date.parse(b.end) / 60_000) * 60_000).toISOString()
        : undefined;
      return api.aiUsage(clamps && read ? read.start : b.start, end);
    },
    placeholderData: clamps ? (previous) => previous : undefined,
    staleTime: 60_000,
  });
  // The Inventory lesson (one answer wins): on each overview read, the table is read again
  // only when its rows count MCP servers by review state differently from the overview,
  // so a new server appears within one fetch and an unchanged picture is never re-read.
  const overviewAt = agentsQ.dataUpdatedAt;
  useEffect(() => {
    if (area !== "agents" || !agents || !usage.data || usage.isFetching) return;
    const rows = usage.data.mcp;
    const stale =
      rows.filter((m) => m.status === "not_approved").length !==
        (agents.mcp_not_approved?.value ?? 0) ||
      rows.filter((m) => m.status === "unreviewed").length !== (agents.mcp_unreviewed ?? 0);
    if (stale) void usage.refetch();
    // Only on a new overview answer: one table read per overview read at most.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overviewAt]);
  // A range too big for the memory share falls back to 24 hours, with the reason (F46).
  const tooBig =
    usage.error instanceof ApiError &&
    usage.error.code === "query_memory" &&
    time.choice.preset !== "24h";
  const fallback = useQuery({
    queryKey: ["ai-usage", "24h"],
    queryFn: () => api.aiUsage(new Date(Date.now() - 86_400_000).toISOString()),
    staleTime: 60_000,
    enabled: tooBig && wantUsage,
  });
  const shown = tooBig ? "24h" : time.choice.preset;
  const setService = useMutation({
    mutationFn: (v: { id: string; status: AiStatus }) => api.setAiServiceStatus(v.id, v.status),
    onSuccess: () => {
      // Covers the Inventory, which lists the same status, and the rail's count of it.
      void client.invalidateQueries({ queryKey: ["ai-usage"] });
    },
  });
  const setLevel = useMutation({
    mutationFn: (v: { id: string; level: DataLevel | null }) => api.setAiDataLevel(v.id, v.level),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["ai-usage"] }),
  });
  const setMcp = useMutation({
    mutationFn: (v: { name: string; status: AiStatus }) =>
      api.setAiMcpRule(v.name, v.status === "unreviewed" ? null : v.status),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["ai-usage"] });
      void client.invalidateQueries({ queryKey: ["ai-mcp-rules"] });
      // The strip's Not-approved tile and Needs attention count MCP servers too.
      void client.invalidateQueries({ queryKey: ["agents-overview"] });
    },
  });
  const data = tooBig ? fallback.data : usage.data;
  // The first load can take seconds on a busy install: rows hold the place meanwhile, so
  // a table is never drawn empty before its data is there.
  const loading = !data && !(tooBig ? fallback.isError : usage.isError);
  // Services and MCP servers are said apart (owner, 2026-11-08): "2 not approved" read as
  // two services when one was an MCP server.
  const svcRefused = data?.services.filter((s) => s.service.status === "not_approved").length ?? 0;
  const mcpRefused = data?.mcp.filter((m) => m.status === "not_approved").length ?? 0;
  const notApproved = [
    svcRefused ? `${svcRefused} ${svcRefused === 1 ? "service" : "services"}` : "",
    mcpRefused ? `${mcpRefused} ${mcpRefused === 1 ? "MCP server" : "MCP servers"}` : "",
  ]
    .filter(Boolean)
    .join(" and ");
  const sensitive = data?.people.reduce((n, p) => n + p.sensitive, 0) ?? 0;
  // Claude Code users are people the plugin (telemetry or hooks) saw; network-only rows are
  // people who reached Claude on the network with no plugin record (owner 2026-11-02).
  const codeUsers = data?.people.filter((p) => p.seen_through !== "network").length ?? 0;
  const networkOnly = data?.claude_seen?.network ?? 0;
  const onInventory = area === "ai" && tab === "inventory";
  // The Inventory's numbers (D258), the same as the rail's: from the Inventory on its tab,
  // from the count on the other tabs of AI usage (at once: Needs attention states them).
  const counts = useAiInventoryCounts(area === "ai" && !onInventory);
  const toReview = counts?.toReview ?? null;
  // The Inventory's exports sit in the header and export the view on screen.
  const exporter = useRef<InventoryExport | null>(null);
  const [invRows, setInvRows] = useState<number | null>(null);
  // The page's time choice goes along with a Needs attention link to a tab, as the tab
  // links keep it (PageHeader), so coming back to Services or People keeps it.
  const frag = fragmentValues(useSection());
  const withTime = (state: string) => {
    const next = new URLSearchParams(state);
    for (const k of ["time", "from", "to"]) {
      const v = frag.get(k);
      if (v) next.set(k, v);
    }
    return next.toString();
  };
  const exports =
    onInventory && canExport
      ? (["csv", "json"] as const).map((f) => ({
          label: `Export ${f.toUpperCase()}`,
          // Beside the page's title: say it is the Inventory's list, not all of AI usage.
          name: `Export ${f.toUpperCase()} of the items listed below`,
          onClick: () => exporter.current?.(f),
          disabled: !invRows,
          title:
            invRows === null
              ? "Loading items"
              : invRows
                ? `Export the items listed below as ${f.toUpperCase()}`
                : "Nothing to export: no items are listed below",
        }))
      : [];
  // Which row of MCP servers shows its tools: a server's name, or the Built-in group.
  const [toolsOf, setToolsOf] = useState<string | null>(null);
  const builtIn = useBuiltInCount(agentWin, area === "agents" && tab === "mcp");
  // Agents' own numbers in the header (fix list item 14), from the answer the strip's tiles
  // read, so the header and the tiles always say the same.
  const alertsItem = useOpenAlertsItem();
  // Said once, under the time control, when Agents read less than the time chosen.
  const chosen = windowOf(time.choice).from;
  const shorter =
    area === "agents" &&
    read !== null &&
    (chosen === null || Date.parse(read.start) - chosen.getTime() > 60_000);
  // Agents' Needs attention: the MCP servers of the strip's own answer, the same on every
  // tab and the same count as the Not-approved MCP servers tile.
  const mcpNotApproved = agents?.mcp_not_approved?.value ?? 0;
  const mcpUnreviewed = agents?.mcp_unreviewed ?? 0;
  const agentsAttention = attentionItems([
    alertsItem,
    count(
      "mcp-no",
      mcpNotApproved,
      "not approved MCP server in use",
      "not approved MCP servers in use",
      "agents",
      "mcp",
    ),
    count(
      "mcp-un",
      mcpUnreviewed,
      "unreviewed MCP server",
      "unreviewed MCP servers",
      "agents",
      "mcp",
    ),
  ]);
  const agentsCount = agents?.has_source
    ? [
        say(agents.sessions?.value ?? 0, "session", "sessions"),
        say(agents.people?.value ?? 0, "person", "people"),
        say(agents.calls?.value ?? 0, "tool call", "tool calls"),
      ].join(" · ")
    : null;
  // Shown while its count is not known (loading, or failed: the row then opens to the
  // error), when there are built-in calls, and while it is open.
  const builtInRow = builtIn !== 0 || toolsOf === BUILT_IN;
  const newServices = new Set(data?.new_services ?? []);
  const newMcp = new Set(data?.new_mcp ?? []);
  const gone = data?.gone ?? [];
  const before = tooBig ? "previous 24 hours" : time.before;
  // Custom with no start has no earlier period to compare with.
  const comparable = tooBig || time.choice.preset !== "custom" || time.choice.from !== "";
  // Signed in, but no readable sources: say so instead of "add a source" (QA F17).
  const noAccess = !!data && data.sources_in_scope.length === 0 && !isAdmin;
  const noAccessEmpty: CardEmpty = {
    kind: "restricted",
    title: "You cannot read any sources yet.",
    detail: "An administrator grants access to source groups under Settings, Users and access.",
  };
  // "N new, N no longer seen" counts what this area lists: services on AI usage, MCP
  // servers on Agents, so the number equals the New badges and the No longer seen rows.
  const newHere = area === "agents" ? newMcp.size : newServices.size;
  const goneHere = gone.filter((g) => g.kind === (area === "agents" ? "mcp" : "service")).length;

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        title={area === "agents" ? "Agents" : "AI usage"}
        count={
          area === "agents"
            ? agentsCount
            : onInventory
              ? toReview === null
                ? null
                : `${toReview} to review`
              : data
                ? `${data.services.length} services · ${data.mcp.length} MCP servers · ${codeUsers} Claude Code ${codeUsers === 1 ? "user" : "users"}`
                : null
        }
        secondary={exports}
      />
      <div className="flex flex-col gap-3 px-5 py-3">
        {/* While loading its place is held; when the request failed, the error says so
            and no line claims that nothing needs attention. */}
        {area === "agents" ? (
          agents || agentsQ.isLoading ? (
            <NeedsAttention loading={agentsQ.isLoading} items={agentsAttention} />
          ) : null
        ) : !noAccess && (data || loading) ? (
          <NeedsAttention
            loading={loading || counts === null}
            items={attentionItems(
              // The same entries on every tab (owner, 2026-11-16): the Inventory's own
              // numbers, then the sensitive-data signals of the time chosen. What is not
              // approved and in use in the time chosen is the chip beside the time control
              // on Services and People.
              [
                alertsItem,
                count(
                  "review",
                  toReview,
                  "item to review",
                  "items to review",
                  "ai",
                  "inventory",
                  withTime("status=unreviewed"),
                ),
                count(
                  "not-approved",
                  counts?.notApproved,
                  "item marked Not approved",
                  "items marked Not approved",
                  "ai",
                  "inventory",
                  withTime("status=not_approved"),
                ),
                count(
                  "sensitive",
                  sensitive,
                  "sensitive-data signal",
                  "sensitive-data signals",
                  "ai",
                  "people",
                  withTime(""),
                ),
              ],
            )}
          />
        ) : null}
        {/* The Inventory is a fixed 30 days: no time control there, and none of the
            lines about the time chosen (owner, 2026-11-16: no control that does nothing). */}
        {onInventory ? null : (
          <div className="flex flex-wrap items-center gap-3">
            <FilterBar
              label={area === "agents" ? "Filter agents by time" : "Filter AI usage by time"}
              time={time.bar}
              onReset={() => time.bar.onChange("7d")}
              isDefault={time.isDefault}
            />
            {shorter && read ? (
              <span data-agents-window="" className="text-sm text-text-muted">
                Agents shows at most 90 days: {day(read.start)} to {day(read.end)}
              </span>
            ) : null}
            {area === "ai" && notApproved ? (
              <span className="rounded-badge border border-warn px-2 py-px text-sm text-warn">
                {notApproved} not approved in use
              </span>
            ) : null}
            {area === "ai" && sensitive ? (
              <span className="rounded-badge border border-warn px-2 py-0.5 text-sm text-warn">
                {sensitive} sensitive-data {sensitive === 1 ? "signal" : "signals"}
              </span>
            ) : null}
            {/* AI usage's comparison of services; Agents says its own once, above its
                tiles (fix list item 14: the line showed twice). */}
            {area === "ai" && data && !data.compared_from && comparable && !noAccess ? (
              <span className="text-sm text-text-muted">
                Nothing earlier to compare with yet: New and No longer seen start once the {before}{" "}
                has data.
              </span>
            ) : null}
            {area === "ai" && data?.compared_from ? (
              <span className="text-sm text-text-secondary">
                Against the {before}:{" "}
                <span className="font-mono tabular-nums text-text">{newHere}</span> new,{" "}
                <span className="font-mono tabular-nums text-text">{goneHere}</span> no longer seen
              </span>
            ) : null}
          </div>
        )}
        <PeoplePending pending={data?.people_pending_days} of={data?.people_days} />
        {usage.isError ? (
          <div role="alert" className="flex flex-col gap-0.5 text-sm">
            <p className="text-danger">
              {usage.error instanceof ApiError ? usage.error.message : "Could not load AI usage"}
            </p>
            {tooBig ? (
              <p className="text-text-secondary">Showing the last 24 hours instead.</p>
            ) : null}
          </div>
        ) : null}
        {setService.isError || setMcp.isError ? (
          <p role="alert" className="text-sm text-danger">
            {((setService.error ?? setMcp.error) as Error).message}
          </p>
        ) : null}

        <ErrorBoundary key={`${tab}-${shown}`} label="This tab">
          {tab === "services" ? (
            <Card
              title="AI services seen in network logs"
              loading={loading}
              note="DNS, firewall, and proxy logs"
              about="From DNS, firewall, and proxy sources you can read. Matched by domain against the catalog."
              empty={
                noAccess
                  ? noAccessEmpty
                  : data && data.services.length === 0
                    ? {
                        kind: "not-set-up",
                        title: "No AI services in this range.",
                        detail: (
                          <>
                            They come from DNS, firewall, and proxy logs: add one of those as a
                            source (BIND, Unbound, Windows DNS, Palo Alto, FortiGate).{" "}
                            <GoToSources />
                          </>
                        ),
                      }
                    : null
              }
            >
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-text-secondary">
                    <th className={TH}>Service</th>
                    <th className={TH}>Review</th>
                    <th className={TH}>Allowed data</th>
                    <th className={`${TH} text-right`}>People</th>
                    <th className={`${TH} text-right`}>Machines</th>
                    <th className={`${TH} text-right`}>Events</th>
                    <th className={TH}>Last seen</th>
                    <th className={TH}>Who (people, or machines)</th>
                    {isAdmin ? (
                      <th className={TH}>
                        <span className="sr-only">Actions</span>
                      </th>
                    ) : null}
                  </tr>
                </thead>
                <tbody>
                  {(data?.services ?? []).map((u) => (
                    <Fragment key={u.service.id}>
                      <tr className="border-b border-border last:border-0">
                        <td className={TD}>
                          <div className="flex items-center gap-2 font-semibold">
                            <EntityLink
                              kind="service"
                              value={u.service.id}
                              label={u.service.name}
                            />
                            {newServices.has(u.service.id) ? <NewBadge /> : null}
                          </div>
                          <div className="text-text-muted">
                            {u.service.vendor} · {KIND[u.service.kind] ?? u.service.kind}
                          </div>
                          {u.service.vendor === "Anthropic" && data?.claude_seen ? (
                            <SeenSummary seen={data.claude_seen} />
                          ) : null}
                        </td>
                        <td className={TD}>
                          <StatusBadge status={u.service.status} />
                        </td>
                        <td className={TD}>
                          <span className="text-text-secondary">
                            {u.service.data_level ? LEVEL_LABEL[u.service.data_level] : "Not set"}
                          </span>
                        </td>
                        <td className={`${TD} text-right font-mono tabular-nums`}>{u.people}</td>
                        <td className={`${TD} text-right font-mono tabular-nums`}>{u.machines}</td>
                        <td className={`${TD} text-right font-mono tabular-nums`}>
                          {u.events.toLocaleString()}
                        </td>
                        <td className={`${TD} whitespace-nowrap font-mono`}>{when(u.last_seen)}</td>
                        <td className={`${TD} font-mono text-text-secondary`}>
                          <EntityList people={u.top_people} machines={u.top_machines} tab="ai" />
                        </td>
                        {isAdmin ? (
                          <td className={`${TD} text-right`}>
                            <button
                              type="button"
                              aria-label={`Review ${u.service.name}`}
                              aria-expanded={reviewing === u.service.id}
                              onClick={() =>
                                setReviewing(reviewing === u.service.id ? null : u.service.id)
                              }
                              className="text-accent-text hover:underline"
                            >
                              Review
                            </button>
                          </td>
                        ) : null}
                      </tr>
                      {isAdmin && reviewing === u.service.id ? (
                        <tr className="border-b border-border bg-inset">
                          <td colSpan={9} className="px-3 py-2">
                            <div className="flex flex-wrap items-center gap-4">
                              <label className="flex items-center gap-2">
                                <span className="text-text-secondary">Review</span>
                                <StatusPicker
                                  label={u.service.name}
                                  value={u.service.status}
                                  onChange={(status) =>
                                    setService.mutate({ id: u.service.id, status })
                                  }
                                />
                              </label>
                              <label className="flex items-center gap-2">
                                <span className="text-text-secondary">Allowed data</span>
                                <Select
                                  aria-label={`Allowed data for ${u.service.name}`}
                                  value={u.service.data_level ?? ""}
                                  onChange={(v) =>
                                    setLevel.mutate({
                                      id: u.service.id,
                                      level: (v || null) as DataLevel | null,
                                    })
                                  }
                                  options={[
                                    { value: "", label: "Not set" },
                                    ...LEVELS.map((l) => ({ value: l, label: LEVEL_LABEL[l] })),
                                  ]}
                                  className="text-sm"
                                />
                              </label>
                            </div>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </Card>
          ) : null}
          {tab === "services" ? (
            <GoneList items={gone.filter((g) => g.kind === "service")} before={before} />
          ) : null}
          {tab === "services" ? <NotUsageList items={data?.non_usage ?? []} /> : null}

          {tab === "mcp" ? (
            <Card
              title="MCP servers"
              loading={loading}
              note="Installed (endpoint inventory) and used (Claude Code telemetry)."
              empty={
                noAccess
                  ? noAccessEmpty
                  : data && data.mcp.length === 0 && builtIn === 0
                    ? {
                        kind: "not-set-up",
                        title: "No MCP servers yet.",
                        detail: (
                          <>
                            Send Claude Code telemetry, or run the MCP inventory script on
                            endpoints; both go to an OpenTelemetry source. <GoToSources />
                          </>
                        ),
                      }
                    : null
              }
            >
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-text-secondary">
                    <th className={TH}>
                      <span className="sr-only">Tools</span>
                    </th>
                    <th className={TH}>Server</th>
                    <th className={TH}>Review</th>
                    <th className={`${TH} text-right`}>Calls</th>
                    <th className={`${TH} text-right`}>People</th>
                    <th className={`${TH} text-right`}>Installed on</th>
                    <th className={TH}>Clients</th>
                    <th className={TH}>Seen in</th>
                    <th className={TH}>Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.mcp ?? []).map((m) => (
                    <Fragment key={m.name}>
                      <tr className="border-b border-border">
                        <td className={`${TD} w-8`}>
                          <ToolsToggle
                            // A server's figures as a whole: the plugin's records are not
                            // split by the server's own tools.
                            label={`Calls and failures of ${m.name}`}
                            open={toolsOf === m.name}
                            onToggle={() => setToolsOf(toolsOf === m.name ? null : m.name)}
                          />
                        </td>
                        <td className={`${TD} font-mono font-semibold`}>
                          <span className="flex items-center gap-2">
                            {m.name}
                            {newMcp.has(m.name) ? <NewBadge /> : null}
                          </span>
                        </td>
                        <td className={TD}>
                          {isAdmin ? (
                            <StatusPicker
                              label={m.name}
                              value={m.status}
                              onChange={(status) => setMcp.mutate({ name: m.name, status })}
                            />
                          ) : (
                            <StatusBadge status={m.status} />
                          )}
                        </td>
                        <td className={`${TD} text-right font-mono tabular-nums`}>{m.calls}</td>
                        <td className={`${TD} text-right font-mono tabular-nums`}>{m.people}</td>
                        <td className={`${TD} text-right font-mono tabular-nums`}>{m.installs}</td>
                        <td className={TD}>{m.clients.join(", ") || "·"}</td>
                        <td className={TD}>{m.sources.join(", ")}</td>
                        <td className={`${TD} whitespace-nowrap font-mono`}>{when(m.last_seen)}</td>
                      </tr>
                      {toolsOf === m.name ? (
                        <tr className="border-b border-border bg-surface-expand">
                          <td colSpan={9} className="p-0">
                            <ToolRows
                              win={agentWin}
                              label={`Calls and failures of ${m.name}`}
                              pick={(t) => t.mcp && t.tool === m.name}
                            />
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  ))}
                  {/* The tools Claude Code has built in belong to no server: one group row
                      (owner, 2026-11-13), opening to each tool. */}
                  {builtInRow ? (
                    <tr data-row="built-in" className="border-b border-border last:border-0">
                      <td className={`${TD} w-8`}>
                        <ToolsToggle
                          label="Tools of Built-in"
                          open={toolsOf === BUILT_IN}
                          onToggle={() => setToolsOf(toolsOf === BUILT_IN ? null : BUILT_IN)}
                        />
                      </td>
                      <td className={`${TD} font-semibold`}>Built-in</td>
                      <td className={`${TD} text-text-muted`} colSpan={7}>
                        {builtIn === null
                          ? "Tools"
                          : `${builtIn} ${builtIn === 1 ? "tool" : "tools"}`}{" "}
                        of Claude Code itself (Bash, Read, Edit and others); not reviewed.
                      </td>
                    </tr>
                  ) : null}
                  {builtInRow && toolsOf === BUILT_IN ? (
                    <tr className="bg-surface-expand">
                      <td colSpan={9} className="p-0">
                        <ToolRows win={agentWin} label="Built-in tools" pick={(t) => !t.mcp} />
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </Card>
          ) : null}
          {tab === "mcp" ? (
            <GoneList items={gone.filter((g) => g.kind === "mcp")} before={before} />
          ) : null}

          {tab === "people" ? (
            <Card
              title="Claude Code by person"
              loading={loading}
              note="Claude Code telemetry and network logs"
              about="From Claude Code telemetry and the hooks plugin; network rows are people seen reaching Claude on DNS, firewall, or proxy logs. Cost is Claude Code's own estimate in USD."
              // D242: the server sent machines in place of names.
              notice={data?.masked ? NAMES_HIDDEN : null}
              lead={
                networkOnly ? (
                  <span className="tabular-nums text-text-primary">
                    Seen on the network but no plugin: {networkOnly}. Sessions, tool calls, and
                    errors need the plugin.
                  </span>
                ) : null
              }
              empty={
                noAccess
                  ? noAccessEmpty
                  : data && data.people.length === 0
                    ? {
                        kind: "not-set-up",
                        title: "No Claude Code telemetry in this range.",
                        detail: (
                          <>
                            Add an OpenTelemetry source and point Claude Code at it
                            (docs/install/claude-code-telemetry.md). <GoToSources />
                          </>
                        ),
                      }
                    : null
              }
            >
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-text-secondary">
                    <th className={`${TH} whitespace-nowrap`}>Person</th>
                    <th className={`${TH} whitespace-nowrap`}>Seen through</th>
                    <th className={`${TH} whitespace-nowrap text-right`}>Cost (USD)</th>
                    <th className={`${TH} whitespace-nowrap text-right`}>Tokens</th>
                    <th className={`${TH} whitespace-nowrap text-right`}>Sessions</th>
                    <th className={`${TH} whitespace-nowrap text-right`}>Tool calls</th>
                    <th className={`${TH} whitespace-nowrap text-right`}>Errors</th>
                    <th className={`${TH} whitespace-nowrap`}>Sensitive data</th>
                    <th className={`${TH} whitespace-nowrap`}>Models</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.people ?? []).map((p) => (
                    <tr key={p.key} className="border-b border-border last:border-0">
                      {/* 22 characters at least, so an email never breaks inside a word (D257). */}
                      <td className={`${TD} min-w-[22ch] font-mono`}>
                        {data?.masked ? (
                          // A machine (or "Hidden"), not a person: plain text, no person link.
                          p.person
                        ) : (
                          <EntityLink kind="user" value={p.person} tab="ai" />
                        )}
                        {p.seen_through === "network" ? (
                          <Unmatched p={p} isAdmin={isAdmin} />
                        ) : null}
                      </td>
                      <td className={TD}>
                        <span title={seenTitle(p)}>{SEEN[p.seen_through ?? "plugin"]}</span>
                        {p.seen_through === "network" ? <NetworkSeen p={p} /> : null}
                      </td>
                      {p.seen_through === "network" ? (
                        // Network only (D190): what the network gives stays under Seen
                        // through, cost and tokens say Not reported as for any person
                        // without telemetry, and the counts are empty with the reason on
                        // hover, so no text runs across the columns (fix list 22).
                        <>
                          {(["Cost", "Tokens"] as const).map((c) => (
                            <td key={c} className={`${TD} text-right`}>
                              <NotReported />
                            </td>
                          ))}
                          {(["Sessions", "Tool calls", "Errors"] as const).map((c) => (
                            <td
                              key={c}
                              title={NETWORK_GIVES}
                              className={`${TD} text-right text-text-muted`}
                            >
                              ·
                            </td>
                          ))}
                        </>
                      ) : (
                        <>
                          <td className={`${TD} text-right font-mono tabular-nums`}>
                            {!reportsCost(p) ? (
                              <NotReported />
                            ) : p.cost_reported === false ? (
                              <NoCostData />
                            ) : typeof p.cost_usd === "number" && Number.isFinite(p.cost_usd) ? (
                              p.cost_usd.toFixed(2)
                            ) : (
                              "·"
                            )}
                          </td>
                          <td className={`${TD} text-right font-mono tabular-nums`}>
                            {!reportsCost(p) ? (
                              <NotReported />
                            ) : p.cost_reported === false ? (
                              <NoCostData />
                            ) : (
                              p.tokens.toLocaleString()
                            )}
                          </td>
                          <td className={`${TD} text-right font-mono tabular-nums`}>
                            {p.sessions}
                          </td>
                          <td className={`${TD} text-right font-mono tabular-nums`}>
                            {p.tool_calls}
                          </td>
                          <td className={`${TD} text-right font-mono tabular-nums`}>{p.errors}</td>
                        </>
                      )}
                      <td className={TD}>
                        {p.sensitive ? (
                          <span className="rounded-badge border border-warn px-1.5 py-px text-warn">
                            {p.sensitive} {p.sensitive === 1 ? "signal" : "signals"}
                          </span>
                        ) : (
                          <span className="text-text-muted">None</span>
                        )}
                      </td>
                      <td className={`${TD} font-mono text-text-secondary`}>
                        {p.models.join(", ") || "·"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          ) : null}

          {tab === "sessions" ? (
            <div className="flex flex-col gap-3">
              {/* The numbers that were the Overview tab (ADR-0052 section 3.3). */}
              <AgentsKpis win={agentWin} />
              <AgentsCard />
              <SessionsCard win={agentWin} />
            </div>
          ) : null}

          {tab === "accounts" ? <AccountsCard win={agentWin} /> : null}

          {tab === "inventory" ? (
            <InventoryCard isAdmin={isAdmin} exporter={exporter} onRows={setInvRows} />
          ) : null}
        </ErrorBoundary>
      </div>
    </div>
  );
}

/** Cost and tokens come from Claude Code telemetry only; the hooks plugin and the
 * network do not report them (D190). */
function reportsCost(p: AiPerson): boolean {
  return (p.via ?? []).includes("telemetry");
}

function NotReported() {
  return (
    <span
      className="whitespace-nowrap font-sans text-text-muted"
      title="Not reported by the hooks plugin or the network: only Claude Code telemetry reports cost and tokens"
    >
      Not reported
    </span>
  );
}

const NETWORK_GIVES =
  "Seen only on the network: DNS, firewall, and proxy logs do not report sessions, tool calls, or errors";

/** Telemetry arrived but no cost or token metric did: unknown, never "0.00" (owner,
 * 2026-11-08). Usually the metrics exporter is not turned on. "None received", apart from
 * "Not reported": this source does report cost and tokens, and none arrived. */
function NoCostData() {
  return (
    <span
      className="whitespace-nowrap font-sans text-text-muted"
      title="Claude Code telemetry reports cost and tokens, but none arrived for this person. Check that the metrics exporter is turned on."
    >
      None received
    </span>
  );
}

/** What the network saw of a person seen only there (D190): the services, lookups,
 * devices, and last seen, under "Network" in its own column (fix list 22). */
function NetworkSeen({ p }: { p: AiPerson }) {
  const n = p.network;
  if (!n) return null;
  return (
    <span className="mt-0.5 flex flex-col text-xs text-text-secondary">
      <span>{n.services.join(", ") || "Claude"}</span>
      <span className="tabular-nums">
        {n.lookups.toLocaleString()} {n.lookups === 1 ? "lookup" : "lookups"}, {n.devices}{" "}
        {n.devices === 1 ? "device" : "devices"}
      </span>
      <span>
        Last seen <When iso={n.last_seen} />
      </span>
    </span>
  );
}

/** Under a network-only name: not linked to a person, the plugin person it may be, and
 * for admins a link to Identities with both filled in (D190). */
function Unmatched({ p, isAdmin }: { p: AiPerson; isAdmin: boolean }) {
  const alias = p.network?.who ?? p.person;
  return (
    <span className="mt-0.5 flex flex-col font-sans text-xs text-text-muted">
      {p.maybe ? (
        <span>
          Unmatched: may be <span className="font-mono">{p.maybe}</span>
        </span>
      ) : (
        <span>Unmatched: not linked to a person</span>
      )}
      {isAdmin ? (
        <a
          href={`${pathFor("identities")}#${identityHash(alias, p.maybe ?? "")}`}
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey) return;
            e.preventDefault();
            navigate("identities", identityHash(alias, p.maybe ?? ""));
          }}
          className="w-fit text-accent-text hover:underline"
        >
          Link in Identities
        </a>
      ) : (
        <span>An administrator can link them in Identities.</span>
      )}
    </span>
  );
}

function identityHash(alias: string, person: string): string {
  return `alias=${encodeURIComponent(alias)}&person=${encodeURIComponent(person)}`;
}

function NewBadge() {
  return (
    <span className="rounded-badge bg-accent-subtle px-1.5 py-px text-xs font-normal text-accent-text">
      New
    </span>
  );
}

function GoToSources() {
  return (
    <button
      type="button"
      onClick={() => navigate("sources")}
      className="text-accent-text hover:underline"
    >
      Go to Sources
    </button>
  );
}

/** Seen in the period before the range and not in it. An approved one nobody uses any
 * more is worth a review: access that is not needed can be taken away. */
function GoneList({ items, before }: { items: AiGone[]; before: string }) {
  if (items.length === 0) return null;
  return (
    <SharedCard title="No longer seen" note={`Seen in the ${before}, not in this range`}>
      <p className="border-b border-border px-3 py-1.5 text-sm text-text-secondary">
        If an approved one is no longer needed, consider removing its approval or access.
      </p>
      <ul>
        {items.map((g) => (
          <li
            key={`${g.kind}-${g.id}`}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-3 py-2 text-sm last:border-0"
          >
            <span className={`min-w-0 font-semibold ${g.kind === "mcp" ? "font-mono" : ""}`}>
              {g.name}
            </span>
            <StatusBadge status={g.status} />
            <span className="ml-auto whitespace-nowrap font-mono text-text-secondary">
              Last seen {when(g.last_seen)}
            </span>
          </li>
        ))}
      </ul>
    </SharedCard>
  );
}

/** Vendor hosts other websites load (ad and measurement tags): matched so they are not
 * mistaken for the vendor's service, shown here, and never counted as AI use. */
function NotUsageList({ items }: { items: AiServiceUse[] }) {
  if (items.length === 0) return null;
  const events = items.reduce((n, u) => n + u.events, 0);
  return (
    <SharedCard
      title="Not counted as AI use"
      note={`${items.length} ${items.length === 1 ? "host group" : "host groups"}, ${events.toLocaleString()} events`}
    >
      <details aria-label="Hosts not counted as AI use">
        <summary className="cursor-pointer px-3 py-2 text-sm text-text-secondary">
          <span>
            Vendor ad and measurement tags that other websites load. They are not someone using the
            service.
          </span>
        </summary>
        <table className="w-full border-t border-border text-sm">
          <thead>
            <tr className="border-b border-border text-text-secondary">
              <th className={TH}>Hosts</th>
              <th className={`${TH} text-right`}>Machines</th>
              <th className={`${TH} text-right`}>Events</th>
              <th className={TH}>Last seen</th>
            </tr>
          </thead>
          <tbody>
            {items.map((u) => (
              <tr key={u.service.id} className="border-b border-border last:border-0">
                <td className={TD}>
                  <div className="font-semibold">{u.service.name}</div>
                  <div className="font-mono text-text-muted">{u.service.domains.join(", ")}</div>
                </td>
                <td className={`${TD} text-right font-mono tabular-nums`}>{u.machines}</td>
                <td className={`${TD} text-right font-mono tabular-nums`}>
                  {u.events.toLocaleString()}
                </td>
                <td className={`${TD} whitespace-nowrap font-mono`}>{when(u.last_seen)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </SharedCard>
  );
}

/** Why a card has no rows: the viewer reads no source, or the install lacks one. */
interface CardEmpty {
  kind: "restricted" | "not-set-up";
  title: string;
  detail: ReactNode;
}

interface CardProps {
  title: string;
  note: ReactNode;
  /** How the rows are counted, behind the (i) beside the title. */
  about?: string;
  /** A state notice above the rows (names hidden, D242). */
  notice?: string | null;
  /** A line above the rows: a count beside the note, or the names-hidden notice. */
  lead?: ReactNode;
  empty: CardEmpty | null;
  /** The data is not here yet: skeleton rows, never an empty table. */
  loading: boolean;
  children: ReactNode;
}

function Card({ title, note, about, notice, lead, empty, loading, children }: CardProps) {
  return (
    <SharedCard title={title} note={note} about={about}>
      {notice ? (
        <div className="border-b border-border p-2">
          <StateNotice>{notice}</StateNotice>
        </div>
      ) : null}
      {lead ? (
        <div className="border-b border-border px-3 py-1.5 text-sm text-text-secondary">{lead}</div>
      ) : null}
      {loading ? (
        // The loaded card's shape: a header row and two-line rows, so nothing grows on arrival.
        <Skeleton label={title} rows={5} header tall className="rounded-none border-0" />
      ) : empty ? (
        <EmptyState kind={empty.kind} title={empty.title} detail={empty.detail} />
      ) : (
        <div className="overflow-x-auto">{children}</div>
      )}
    </SharedCard>
  );
}
