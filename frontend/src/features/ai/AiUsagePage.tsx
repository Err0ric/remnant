import { EntityLink, EntityList } from "@/components/EntityLink";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { PeoplePending } from "@/components/PeoplePending";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Command, PageHeader } from "@/components/shell/PageHeader";
import {
  ApiError,
  api,
  type AiGone,
  type AiServiceUse,
  type AiStatus,
  type DataLevel,
} from "@/lib/api";
import { rangeStart, TIME_RANGES, type TimeRangeId } from "@/lib/search";
import { navigate, useSectionTab } from "@/lib/route";
import { AgentsCard } from "./AgentsCard";
import { SessionsCard } from "./SessionsCard";
import { AccountsCard } from "./AccountsCard";
import { AiSettings } from "./AiSettings";
import { StatusBadge, StatusPicker } from "./StatusBadge";

type Tab = "services" | "agents" | "mcp" | "accounts" | "people" | "settings";
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

function when(iso: string | null): string {
  return iso ? iso.slice(0, 16).replace("T", " ") : "·";
}

const TH = "px-3 py-2 text-left font-semibold";
const TD = "px-3 py-2 align-top";

interface AiUsagePageProps {
  isAdmin: boolean;
  /** AI usage (services, people, review) or Agents (sessions, MCP servers); ADR-0038. */
  area?: "ai" | "agents";
}

/** AI usage (ADR-0015 row 8): services, agents and MCP servers, and Claude usage. */
export function AiUsagePage({ isAdmin, area = "ai" }: AiUsagePageProps) {
  const client = useQueryClient();
  const [range, setRange] = useState<TimeRangeId>("7d");
  const usage = useQuery({
    queryKey: ["ai-usage", range],
    queryFn: () => api.aiUsage(rangeStart(range)),
    staleTime: 60_000,
  });
  // A range too big for the memory share falls back to 24 hours, with the reason (F46).
  const tooBig =
    usage.error instanceof ApiError && usage.error.code === "query_memory" && range !== "24h";
  const fallback = useQuery({
    queryKey: ["ai-usage", "24h"],
    queryFn: () => api.aiUsage(rangeStart("24h")),
    staleTime: 60_000,
    enabled: tooBig,
  });
  const shown: TimeRangeId = tooBig ? "24h" : range;
  const setService = useMutation({
    mutationFn: (v: { id: string; status: AiStatus }) => api.setAiServiceStatus(v.id, v.status),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["ai-usage"] }),
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
    },
  });
  const tabs: Tab[] =
    area === "agents"
      ? ["agents", "mcp", "accounts"]
      : isAdmin
        ? ["services", "people", "settings"]
        : ["services", "people"];
  const [tab] = useSectionTab<Tab>(tabs);
  const data = tooBig ? fallback.data : usage.data;
  const notApproved =
    (data?.services.filter((s) => s.service.status === "not_approved").length ?? 0) +
    (data?.mcp.filter((m) => m.status === "not_approved").length ?? 0);
  const sensitive = data?.people.reduce((n, p) => n + p.sensitive, 0) ?? 0;
  const newServices = new Set(data?.new_services ?? []);
  const newMcp = new Set(data?.new_mcp ?? []);
  const fresh = newServices.size + newMcp.size;
  const gone = data?.gone ?? [];
  const label = TIME_RANGES.find((r) => r.id === shown)?.label ?? "";
  const before = label.replace(/^Last /, "previous ");
  // Signed in, but no readable sources: say so instead of "add a source" (QA F17).
  const noAccess = !!data && data.sources_in_scope.length === 0 && !isAdmin;
  const noAccessText = (
    <>
      You cannot read any sources yet. An administrator grants access to source groups under
      Settings, Users and access.
    </>
  );

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        crumbs={["Home", "AI", "AI usage"]}
        title={area === "agents" ? "Agents" : "AI usage"}
        commands={
          <Command
            label={usage.isFetching ? "Refreshing…" : "Refresh"}
            onClick={() => void usage.refetch()}
            disabled={usage.isFetching}
          />
        }
        meta={
          data
            ? `${data.services.length} services · ${data.mcp.length} MCP servers · ${data.people.length} Claude Code ${data.people.length === 1 ? "user" : "users"}`
            : null
        }
      />
      <div className="flex flex-col gap-3 px-5 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <span className="text-text-secondary">Time range</span>
            <select
              value={range}
              onChange={(e) => setRange(e.target.value as TimeRangeId)}
              className="h-8 rounded border border-border-strong bg-surface px-2 text-sm"
            >
              {TIME_RANGES.filter((r) => r.id !== "15m").map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
          {notApproved ? (
            <span className="rounded-badge bg-sev-critical-bg px-2 py-0.5 text-sm text-sev-critical-text">
              {notApproved} not approved in use
            </span>
          ) : null}
          {sensitive ? (
            <span className="rounded-badge bg-sev-high-bg px-2 py-0.5 text-sm text-sev-high-text">
              {sensitive} sensitive-data {sensitive === 1 ? "signal" : "signals"}
            </span>
          ) : null}
          {data && !data.compared_from && shown !== "all" && !noAccess ? (
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
                noAccess ? (
                  noAccessText
                ) : data && data.services.length === 0 ? (
                  <>
                    No AI services in this range. They come from DNS, firewall, and proxy logs: add
                    one of those as a source (BIND, Unbound, Windows DNS, Palo Alto, FortiGate).{" "}
                    <GoToSources />
                  </>
                ) : null
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
                    <th className={TH}>Last seen (UTC)</th>
                    <th className={TH}>Who (people, or machines)</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.services ?? []).map((u) => (
                    <tr key={u.service.id} className="border-b border-border last:border-0">
                      <td className={TD}>
                        <div className="flex items-center gap-2 font-semibold">
                          <EntityLink kind="service" value={u.service.id} label={u.service.name} />
                          {newServices.has(u.service.id) ? <NewBadge /> : null}
                        </div>
                        <div className="text-text-muted">
                          {u.service.vendor} · {KIND[u.service.kind] ?? u.service.kind}
                        </div>
                      </td>
                      <td className={TD}>
                        {isAdmin ? (
                          <StatusPicker
                            label={u.service.name}
                            value={u.service.status}
                            onChange={(status) => setService.mutate({ id: u.service.id, status })}
                          />
                        ) : (
                          <StatusBadge status={u.service.status} />
                        )}
                      </td>
                      <td className={TD}>
                        {isAdmin ? (
                          <select
                            aria-label={`Allowed data for ${u.service.name}`}
                            value={u.service.data_level ?? ""}
                            onChange={(e) =>
                              setLevel.mutate({
                                id: u.service.id,
                                level: (e.target.value || null) as DataLevel | null,
                              })
                            }
                            className="h-8 rounded border border-border-strong bg-inset px-2 text-sm"
                          >
                            <option value="">Not set</option>
                            {LEVELS.map((l) => (
                              <option key={l} value={l}>
                                {LEVEL_LABEL[l]}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="text-text-secondary">
                            {u.service.data_level ? LEVEL_LABEL[u.service.data_level] : "Not set"}
                          </span>
                        )}
                      </td>
                      <td className={`${TD} text-right font-mono tabular-nums`}>{u.people}</td>
                      <td className={`${TD} text-right font-mono tabular-nums`}>{u.machines}</td>
                      <td className={`${TD} text-right font-mono tabular-nums`}>
                        {u.events.toLocaleString()}
                      </td>
                      <td className={`${TD} whitespace-nowrap font-mono`}>{when(u.last_seen)}</td>
                      <td className={`${TD} font-mono text-text-secondary`}>
                        <EntityList people={u.top_people} machines={u.top_machines} />
                      </td>
                    </tr>
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
                noAccess ? (
                  noAccessText
                ) : data && data.mcp.length === 0 ? (
                  <>
                    No MCP servers yet. Send Claude Code telemetry, or run the MCP inventory script
                    on endpoints; both go to an OpenTelemetry source. <GoToSources />
                  </>
                ) : null
              }
            >
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-text-secondary">
                    <th className={TH}>Server</th>
                    <th className={TH}>Review</th>
                    <th className={`${TH} text-right`}>Calls</th>
                    <th className={`${TH} text-right`}>People</th>
                    <th className={`${TH} text-right`}>Installed on</th>
                    <th className={TH}>Clients</th>
                    <th className={TH}>Seen in</th>
                    <th className={TH}>Last seen (UTC)</th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.mcp ?? []).map((m) => (
                    <tr key={m.name} className="border-b border-border last:border-0">
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
                  ))}
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
              note="From Claude Code telemetry. Cost is Claude Code's own estimate in USD."
              empty={
                noAccess ? (
                  noAccessText
                ) : data && data.people.length === 0 ? (
                  <>
                    No Claude Code telemetry in this range. Add an OpenTelemetry source and point
                    Claude Code at it (docs/install/claude-code-telemetry.md). <GoToSources />
                  </>
                ) : null
              }
            >
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-text-secondary">
                    <th className={TH}>Person</th>
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
                    <tr key={p.person} className="border-b border-border last:border-0">
                      <td className={`${TD} font-mono`}>
                        <EntityLink kind="user" value={p.person} />
                      </td>
                      <td className={`${TD} text-right font-mono tabular-nums`}>
                        {typeof p.cost_usd === "number" && Number.isFinite(p.cost_usd)
                          ? p.cost_usd.toFixed(2)
                          : "·"}
                      </td>
                      <td className={`${TD} text-right font-mono tabular-nums`}>
                        {p.tokens.toLocaleString()}
                      </td>
                      <td className={`${TD} text-right font-mono tabular-nums`}>{p.sessions}</td>
                      <td className={`${TD} text-right font-mono tabular-nums`}>{p.tool_calls}</td>
                      <td className={`${TD} text-right font-mono tabular-nums`}>{p.errors}</td>
                      <td className={TD}>
                        {p.sensitive ? (
                          <span className="rounded-badge bg-sev-high-bg px-1.5 py-px text-sev-high-text">
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

          {tab === "agents" ? (
            <div className="flex flex-col gap-3">
              <AgentsCard />
              <SessionsCard />
            </div>
          ) : null}

          {tab === "accounts" ? <AccountsCard /> : null}

          {tab === "settings" && isAdmin ? <AiSettings /> : null}
        </ErrorBoundary>
      </div>
    </div>
  );
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
        <h2 className="text-base font-semibold">No longer seen</h2>
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
              Last seen {when(g.last_seen)} UTC
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
        <h2 className="text-base font-semibold">Not counted as AI use</h2>
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
            <th className={TH}>Last seen (UTC)</th>
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

interface CardProps {
  title: string;
  note: string;
  empty: ReactNode;
  children: ReactNode;
}

function Card({ title, note, empty, children }: CardProps) {
  return (
    <section
      aria-label={title}
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-surface-head px-3 py-2">
        <h2 className="text-base font-semibold">{title}</h2>
        <span className="text-sm text-text-muted">{note}</span>
      </div>
      {empty ? (
        <p className="px-3 py-6 text-center text-sm text-text-secondary">{empty}</p>
      ) : (
        <div className="overflow-x-auto">{children}</div>
      )}
    </section>
  );
}
