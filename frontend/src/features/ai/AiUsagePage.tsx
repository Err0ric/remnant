import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type KeyboardEvent, type ReactNode } from "react";
import { Command, PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api, type AiStatus } from "@/lib/api";
import { rangeStart, TIME_RANGES, type TimeRangeId } from "@/lib/search";
import { navigate } from "@/lib/route";
import { AiSettings } from "./AiSettings";
import { StatusBadge, StatusPicker } from "./StatusBadge";

type Tab = "services" | "mcp" | "people" | "settings";
const LABELS: Record<Tab, string> = {
  services: "Services",
  mcp: "Agents and MCP",
  people: "Claude usage",
  settings: "Review and alerts",
};
const KIND: Record<string, string> = {
  chat: "Chat",
  api: "API",
  coding: "Coding",
  agent_platform: "Agent builder",
  mcp_registry: "MCP registry",
  image: "Image and voice",
  meetings: "Meetings",
  writing: "Writing",
};

function when(iso: string | null): string {
  return iso ? iso.slice(0, 16).replace("T", " ") : "·";
}

const TH = "px-3 py-2 text-left font-semibold";
const TD = "px-3 py-2 align-top";

interface AiUsagePageProps {
  isAdmin: boolean;
}

/** AI usage (ADR-0015 row 8): services, agents and MCP servers, and Claude usage. */
export function AiUsagePage({ isAdmin }: AiUsagePageProps) {
  const client = useQueryClient();
  const [tab, setTab] = useState<Tab>("services");
  const [range, setRange] = useState<TimeRangeId>("7d");
  const usage = useQuery({
    queryKey: ["ai-usage", range],
    queryFn: () => api.aiUsage(rangeStart(range)),
    staleTime: 60_000,
  });
  const setService = useMutation({
    mutationFn: (v: { id: string; status: AiStatus }) => api.setAiServiceStatus(v.id, v.status),
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
  const tabs: Tab[] = isAdmin
    ? ["services", "mcp", "people", "settings"]
    : ["services", "mcp", "people"];
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const i = tabs.indexOf(tab);
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    if (next) {
      setTab(next);
      document.getElementById(`ai-tab-${next}`)?.focus();
    }
  };
  const data = usage.data;
  const notApproved =
    (data?.services.filter((s) => s.service.status === "not_approved").length ?? 0) +
    (data?.mcp.filter((m) => m.status === "not_approved").length ?? 0);
  const sensitive = data?.people.reduce((n, p) => n + p.sensitive, 0) ?? 0;

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        crumbs={["Home", "Detect", "AI usage"]}
        title="AI usage"
        commands={
          <Command
            label={usage.isFetching ? "Refreshing…" : "Refresh"}
            onClick={() => void usage.refetch()}
            disabled={usage.isFetching}
          />
        }
        meta={
          data
            ? `${data.services.length} services · ${data.mcp.length} MCP servers · ${data.people.length} people`
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
        </div>
        <div
          role="tablist"
          aria-label="AI usage"
          onKeyDown={onKey}
          className="flex gap-1 border-b border-border"
        >
          {tabs.map((t) => (
            <button
              key={t}
              id={`ai-tab-${t}`}
              type="button"
              role="tab"
              aria-selected={tab === t}
              tabIndex={tab === t ? 0 : -1}
              onClick={() => setTab(t)}
              className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${
                tab === t
                  ? "border-accent font-semibold text-text"
                  : "border-transparent text-text-secondary hover:text-text"
              }`}
            >
              {LABELS[t]}
            </button>
          ))}
        </div>
        {usage.isError ? (
          <p role="alert" className="text-sm text-danger">
            {usage.error instanceof ApiError ? usage.error.message : "Could not load AI usage"}
          </p>
        ) : null}
        {setService.isError || setMcp.isError ? (
          <p role="alert" className="text-sm text-danger">
            {((setService.error ?? setMcp.error) as Error).message}
          </p>
        ) : null}

        {tab === "services" ? (
          <Card
            title="AI services seen in network logs"
            note="From DNS, firewall, and proxy sources you can read. Matched by domain against the catalog."
            empty={
              data && data.services.length === 0 ? (
                <>
                  No AI services in this range. They come from DNS, firewall, and proxy logs: add
                  one of those as a source (BIND, Unbound, Windows DNS, Palo Alto, FortiGate).
                </>
              ) : null
            }
          >
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-text-secondary">
                  <th className={TH}>Service</th>
                  <th className={TH}>Review</th>
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
                      <div className="font-semibold">{u.service.name}</div>
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
                    <td className={`${TD} text-right font-mono tabular-nums`}>{u.people}</td>
                    <td className={`${TD} text-right font-mono tabular-nums`}>{u.machines}</td>
                    <td className={`${TD} text-right font-mono tabular-nums`}>
                      {u.events.toLocaleString()}
                    </td>
                    <td className={`${TD} whitespace-nowrap font-mono`}>{when(u.last_seen)}</td>
                    <td className={`${TD} font-mono text-text-secondary`}>
                      {u.top_people.join(", ") || u.top_machines.join(", ") || "·"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        ) : null}

        {tab === "mcp" ? (
          <Card
            title="MCP servers"
            note="Installed (endpoint inventory) and used (Claude Code telemetry)."
            empty={
              data && data.mcp.length === 0 ? (
                <>
                  No MCP servers yet. Send Claude Code telemetry, or run the MCP inventory script on
                  endpoints; both go to an OpenTelemetry source.{" "}
                  <button
                    type="button"
                    onClick={() => navigate("sources")}
                    className="text-accent-text hover:underline"
                  >
                    Go to Sources
                  </button>
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
                    <td className={`${TD} font-mono font-semibold`}>{m.name}</td>
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

        {tab === "people" ? (
          <Card
            title="Claude Code by person"
            note="From Claude Code telemetry. Cost is Claude Code's own estimate in USD."
            empty={
              data && data.people.length === 0 ? (
                <>
                  No Claude Code telemetry in this range. The setup is in
                  docs/install/claude-code-telemetry.md.
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
                    <td className={`${TD} font-mono`}>{p.person}</td>
                    <td className={`${TD} text-right font-mono tabular-nums`}>
                      {p.cost_usd.toFixed(2)}
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

        {tab === "settings" && isAdmin ? <AiSettings /> : null}
      </div>
    </div>
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
