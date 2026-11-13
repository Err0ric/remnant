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
import { Fragment, useState, type ReactNode } from "react";
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
import { navigate, pathFor, useSectionTab } from "@/lib/route";
import { When } from "@/components/When";
import { AgentsCard } from "./AgentsCard";
import { SessionsCard } from "./SessionsCard";
import { AccountsCard } from "./AccountsCard";
import { AgentsKpis, ToolRows, useBuiltInCount } from "./AgentsOverview";
import { InventoryCard, toReview } from "./InventoryCard";
import { StatusBadge, StatusPicker } from "./StatusBadge";
import { SectionTitle } from "@/components/SectionTitle";

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
      Seen through: both {seen.both ?? 0}, plugin only {seen.plugin ?? 0}, network only{" "}
      {seen.network ?? 0}
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
  const usage = useQuery({
    queryKey: ["ai-usage", ...time.key],
    queryFn: () => {
      const b = time.bounds();
      // This endpoint reads its bounds to the minute (it caches by them), and its end is
      // inclusive: the start of the next minute keeps the minute Custom's end names.
      const end = b.end
        ? new Date(Math.ceil(Date.parse(b.end) / 60_000) * 60_000).toISOString()
        : undefined;
      return api.aiUsage(b.start, end);
    },
    staleTime: 60_000,
  });
  // A range too big for the memory share falls back to 24 hours, with the reason (F46).
  const tooBig =
    usage.error instanceof ApiError &&
    usage.error.code === "query_memory" &&
    time.choice.preset !== "24h";
  const fallback = useQuery({
    queryKey: ["ai-usage", "24h"],
    queryFn: () => api.aiUsage(new Date(Date.now() - 86_400_000).toISOString()),
    staleTime: 60_000,
    enabled: tooBig,
  });
  const shown = tooBig ? "24h" : time.choice.preset;
  const setService = useMutation({
    mutationFn: (v: { id: string; status: AiStatus }) => api.setAiServiceStatus(v.id, v.status),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["ai-usage"] });
      // The Inventory lists the same status and counts what is left to review.
      void client.invalidateQueries({ queryKey: ["ai-inventory"] });
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
      void client.invalidateQueries({ queryKey: ["ai-inventory"] });
    },
  });
  const tabs: Tab[] =
    area === "agents" ? ["sessions", "mcp", "accounts"] : ["services", "people", "inventory"];
  const [tab] = useSectionTab<Tab>(tabs);
  const data = tooBig ? fallback.data : usage.data;
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
  const servicesNotApproved =
    data?.services.filter((s) => s.service.status === "not_approved").length ?? 0;
  const servicesUnreviewed =
    data?.services.filter((s) => s.service.status === "unreviewed").length ?? 0;
  const mcpNotApproved = data?.mcp.filter((m) => m.status === "not_approved").length ?? 0;
  const mcpUnreviewed = data?.mcp.filter((m) => m.status === "unreviewed").length ?? 0;
  // On Inventory the header says how many items wait for a review (ADR-0052 section 3.3).
  // The card's own query, shared by key: no second request, and none on the other tabs.
  const onInventory = area === "ai" && tab === "inventory";
  const inventory = useQuery({
    queryKey: ["ai-inventory"],
    queryFn: () => api.aiInventory(30),
    enabled: onInventory,
  });
  // Agents: the strip on Sessions and the tool rows of MCP servers count whole days back
  // from now, so the page's time becomes days (Custom: since its start, 30 at most).
  const agentDays =
    time.choice.preset === "custom"
      ? Math.min(
          30,
          Math.max(
            1,
            Math.ceil(
              (Date.now() - Date.parse(time.bounds().start ?? new Date(0).toISOString())) /
                86_400_000,
            ),
          ),
        )
      : time.choice.preset === "30d"
        ? 30
        : time.choice.preset === "7d"
          ? 7
          : 1;
  // Which row of MCP servers shows its tools: a server's name, or the Built-in group.
  const [toolsOf, setToolsOf] = useState<string | null>(null);
  // In words, from the days actually counted, never from the page's choice: at 1 hour the
  // strip still counts a day.
  const agentWindow = agentDays === 1 ? "24 hours" : `${agentDays} days`;
  const agentBefore = `previous ${agentWindow}`;
  const builtIn = useBuiltInCount(agentDays, area === "agents" && tab === "mcp");
  // Shown while its count is not known (loading, or failed: the row then opens to the
  // error), when there are built-in calls, and while it is open.
  const builtInRow = builtIn !== 0 || toolsOf === BUILT_IN;
  const alertsItem = useOpenAlertsItem();
  const newServices = new Set(data?.new_services ?? []);
  const newMcp = new Set(data?.new_mcp ?? []);
  const fresh = newServices.size + newMcp.size;
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

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        title={area === "agents" ? "Agents" : "AI usage"}
        count={
          onInventory
            ? inventory.data
              ? `${toReview(inventory.data.items)} to review`
              : null
            : data
              ? `${data.services.length} services · ${data.mcp.length} MCP servers · ${codeUsers} Claude Code ${codeUsers === 1 ? "user" : "users"}`
              : null
        }
      />
      <div className="flex flex-col gap-3 px-5 py-3">
        {!noAccess ? (
          <NeedsAttention
            loading={!data}
            items={attentionItems(
              area === "agents"
                ? [
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
                  ]
                : [
                    alertsItem,
                    count(
                      "svc-no",
                      servicesNotApproved,
                      "not approved AI service in use",
                      "not approved AI services in use",
                      "ai",
                    ),
                    count(
                      "svc-un",
                      servicesUnreviewed,
                      "unreviewed AI service",
                      "unreviewed AI services",
                      "ai",
                    ),
                    count(
                      "sensitive",
                      sensitive,
                      "sensitive-data signal",
                      "sensitive-data signals",
                      "ai",
                      "people",
                    ),
                  ],
            )}
          />
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <FilterBar
            label={area === "agents" ? "Filter agents by time" : "Filter AI usage by time"}
            time={time.bar}
            onReset={() => time.bar.onChange("7d")}
            isDefault={time.isDefault}
          />
          {notApproved ? (
            <span className="rounded-badge border border-warn px-2 py-px text-sm text-warn">
              {notApproved} not approved in use
            </span>
          ) : null}
          {sensitive ? (
            <span className="rounded-badge border border-warn px-2 py-0.5 text-sm text-warn">
              {sensitive} sensitive-data {sensitive === 1 ? "signal" : "signals"}
            </span>
          ) : null}
          {data && !data.compared_from && comparable && !noAccess ? (
            <span className="text-sm text-text-muted">
              Nothing earlier to compare with yet: New and No longer seen start once the {before}{" "}
              has data.
            </span>
          ) : null}
          {data?.compared_from ? (
            <span className="text-sm text-text-secondary">
              Against the {before}:{" "}
              <span className="font-mono tabular-nums text-text">{fresh}</span> new,{" "}
              <span className="font-mono tabular-nums text-text">{gone.length}</span> no longer seen
            </span>
          ) : null}
        </div>
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
              note="From DNS, firewall, and proxy sources you can read. Matched by domain against the catalog."
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
                                <select
                                  aria-label={`Allowed data for ${u.service.name}`}
                                  value={u.service.data_level ?? ""}
                                  onChange={(e) =>
                                    setLevel.mutate({
                                      id: u.service.id,
                                      level: (e.target.value || null) as DataLevel | null,
                                    })
                                  }
                                  className="h-8 rounded border border-border-control bg-inset px-2 text-sm"
                                >
                                  <option value="">Not set</option>
                                  {LEVELS.map((l) => (
                                    <option key={l} value={l}>
                                      {LEVEL_LABEL[l]}
                                    </option>
                                  ))}
                                </select>
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
                              days={agentDays}
                              before={agentBefore}
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
                        <ToolRows
                          days={agentDays}
                          before={agentBefore}
                          label="Built-in tools"
                          pick={(t) => !t.mcp}
                        />
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
              note={
                <>
                  From Claude Code telemetry and the hooks plugin; network rows are people seen
                  reaching Claude on DNS, firewall, or proxy logs. Cost is Claude Code's own
                  estimate in USD.
                  {networkOnly ? (
                    <span className="ml-1 tabular-nums text-text-primary">
                      Seen on the network but no plugin: {networkOnly}.
                    </span>
                  ) : null}
                  {data?.masked ? (
                    // D242: the server sent machines in place of names.
                    <span className="ml-1">
                      Names are hidden. An admin can turn on View people in AI usage for you.
                    </span>
                  ) : null}
                </>
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
                    <th className={TH}>Person</th>
                    <th className={TH}>Seen through</th>
                    <th className={`${TH} text-right`}>Cost (USD)</th>
                    <th className={`${TH} text-right`}>Tokens</th>
                    <th className={`${TH} text-right`}>Sessions</th>
                    <th className={`${TH} text-right`}>Tool calls</th>
                    <th className={`${TH} text-right`}>Errors</th>
                    <th className={TH}>Sensitive data</th>
                    <th className={TH}>Models</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.people ?? []).map((p) => (
                    <tr key={p.key} className="border-b border-border last:border-0">
                      <td className={`${TD} font-mono`}>
                        {data?.masked ? (
                          // A machine (or "Hidden"), not a person: plain text, no person link.
                          p.person
                        ) : (
                          <EntityLink kind="user" value={p.person} tab="ai" />
                        )}
                      </td>
                      <td className={TD}>
                        <span title={seenTitle(p)}>{SEEN[p.seen_through ?? "plugin"]}</span>
                      </td>
                      {p.seen_through === "network" ? (
                        // Network only (D190): what the network gives, not empty plugin cells.
                        <td colSpan={5} className={`${TD} text-text-secondary`}>
                          <NetworkOnly p={p} isAdmin={isAdmin} />
                        </td>
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
              <AgentsKpis days={agentDays} before={agentBefore} />
              <AgentsCard />
              <SessionsCard days={agentDays} />
            </div>
          ) : null}

          {tab === "accounts" ? <AccountsCard /> : null}

          {tab === "inventory" ? <InventoryCard isAdmin={isAdmin} canExport={canExport} /> : null}
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
      className="font-sans text-text-muted"
      title="Only Claude Code telemetry reports cost and tokens"
    >
      Not reported
    </span>
  );
}

/** Telemetry arrived but no cost or token metric did: unknown, never "0.00" (owner,
 * 2026-11-08). Usually the metrics exporter is not turned on. */
function NoCostData() {
  return (
    <span
      className="font-sans text-text-muted"
      title="No cost or token metrics arrived from Claude Code telemetry for this person. Check that the metrics exporter is turned on."
    >
      No cost data
    </span>
  );
}

/** A person seen only on the network: the services, lookups, devices, and last seen, and
 * when the name reads as a plugin person, a hint to link them in Identities (D190). */
function NetworkOnly({ p, isAdmin }: { p: AiPerson; isAdmin: boolean }) {
  const n = p.network;
  const alias = n?.who ?? p.person;
  return (
    <span className="flex flex-col gap-0.5">
      {n ? (
        <span>
          Network only: {n.services.join(", ") || "Claude"}, {n.lookups.toLocaleString()}{" "}
          {n.lookups === 1 ? "lookup" : "lookups"}, {n.devices}{" "}
          {n.devices === 1 ? "device" : "devices"}, last seen <When iso={n.last_seen} />
        </span>
      ) : (
        <span>Network only</span>
      )}
      <span className="text-text-muted">
        {p.maybe ? (
          <>
            Unmatched: may be <span className="font-mono">{p.maybe}</span>.{" "}
          </>
        ) : (
          "Unmatched: not linked to a person. "
        )}
        {isAdmin ? (
          <a
            href={`${pathFor("identities")}#${identityHash(alias, p.maybe ?? "")}`}
            onClick={(e) => {
              if (e.metaKey || e.ctrlKey || e.shiftKey) return;
              e.preventDefault();
              navigate("identities", identityHash(alias, p.maybe ?? ""));
            }}
            className="text-accent-text hover:underline"
          >
            Link in Identities
          </a>
        ) : (
          "An administrator can link them in Identities."
        )}
      </span>
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
    <section
      aria-label="No longer seen"
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-surface-head px-3 py-2">
        <SectionTitle>No longer seen</SectionTitle>
        <span className="text-sm text-text-muted">
          Seen in the {before}, not in this range. If an approved one is no longer needed, consider
          removing its approval or access.
        </span>
      </div>
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
    </section>
  );
}

/** Vendor hosts other websites load (ad and measurement tags): matched so they are not
 * mistaken for the vendor's service, shown here, and never counted as AI use. */
function NotUsageList({ items }: { items: AiServiceUse[] }) {
  if (items.length === 0) return null;
  const events = items.reduce((n, u) => n + u.events, 0);
  return (
    <details
      aria-label="Not counted as AI use"
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 bg-surface-head px-3 py-2">
        <SectionTitle>Not counted as AI use</SectionTitle>
        <span className="font-mono text-sm tabular-nums text-text-secondary">
          {items.length} {items.length === 1 ? "host group" : "host groups"},{" "}
          {events.toLocaleString()} events
        </span>
        <span className="text-sm text-text-muted">
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
  empty: CardEmpty | null;
  children: ReactNode;
}

function Card({ title, note, empty, children }: CardProps) {
  return (
    <section
      aria-label={title}
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-surface-head px-3 py-2">
        <SectionTitle>{title}</SectionTitle>
        <span className="text-sm text-text-muted">{note}</span>
      </div>
      {empty ? (
        <EmptyState kind={empty.kind} title={empty.title} detail={empty.detail} />
      ) : (
        <div className="overflow-x-auto">{children}</div>
      )}
    </section>
  );
}
