import { lastDays } from "@/lib/timeWindow";
import { Skeleton } from "@/components/Skeleton";
import { useQuery } from "@tanstack/react-query";
import { COUNTED } from "@/features/dashboard/counted";
import type { ReactNode } from "react";
import { api, type AgentsOverview, type AgentTool } from "@/lib/api";
import { cn } from "@/lib/cn";
import { navigate } from "@/lib/route";
import { EntityLink } from "@/components/EntityLink";
import { InlineError } from "@/components/InlineError";
import { EmptyState } from "@/components/EmptyState";
import { DrillScope, DRILL, Kpi, useDrill } from "@/features/dashboard/Sections";
import { compareLine } from "@/features/dashboard/History";
import { since, stamp } from "@/features/overview/time";
import { StatusBadge } from "./StatusBadge";

/** The numbers behind the Agents page for a number of days back from now, from the hooks
 * plugin: shared by the strip on Sessions and the tool rows of MCP servers. */
export function useAgentsOverview(days: number) {
  return useQuery({
    queryKey: ["agents-overview", days],
    queryFn: () => api.agentsOverview(days),
    refetchInterval: 300_000,
  });
}

interface AgentsKpisProps {
  /** Whole days back from now, from the page's time choice. */
  days: number;
  /** "previous 7 days": what the changes are against. */
  before: string;
}

/** The KPI strip on Agents > Sessions (ADR-0052 section 3.3; it was the Overview tab):
 * six numbers for the page's time, each opening its rows in Logs (ADR-0039). */
export function AgentsKpis({ days, before }: AgentsKpisProps) {
  const q = useAgentsOverview(days);
  const d = q.data;
  if (q.isLoading) return <Skeleton label="the agents numbers" block="h-24" />;
  if (q.isError && !d)
    return (
      <section aria-label="Overview" className="rounded-card border border-border bg-surface">
        <InlineError
          what="The agents numbers"
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
        />
      </section>
    );
  if (!d) return null;
  if (!d.has_source)
    return (
      <EmptyState
        kind="not-set-up"
        title="Needs the hooks plugin"
        detail="Install the Claude Code hooks plugin on the devices to see sessions, tool calls, and MCP servers here. If a hooks source exists, you may not have access to it."
        action={{ label: "Get the plugin", onClick: () => navigate("plugins") }}
      />
    );
  return (
    <DrillScope bounds={d} area="Agents > Sessions" history={d.history} before={before}>
      <span className="text-sm text-text-muted">
        {lastDays(days)}. {compareLine(d.history.compared, d.history.since, before)}
      </span>
      <Overview d={d} />
    </DrillScope>
  );
}

interface ToolRowsProps {
  days: number;
  before: string;
  /** The tools to list: one MCP server's row, or the built-in tools. */
  pick: (t: AgentTool) => boolean;
  label: string;
}

/** The tool rows under a row of MCP servers (ADR-0052 section 3.3; they were the Tools
 * tab): people, devices, calls, failures, and when seen, each opening its events. */
export function ToolRows({ days, before, pick, label }: ToolRowsProps) {
  const q = useAgentsOverview(days);
  const d = q.data;
  const now = new Date().toISOString();
  if (q.isLoading) return <Skeleton label={label} rows={2} className="rounded-none border-0" />;
  if (q.isError && !d)
    return (
      <InlineError
        what={label}
        error={q.error}
        onRetry={() => void q.refetch()}
        retrying={q.isFetching}
      />
    );
  const rows = (d?.tools ?? []).filter(pick);
  if (!d || rows.length === 0)
    return <EmptyState kind="default-empty" title={`No tool calls. ${lastDays(days)}.`} />;
  return (
    <DrillScope bounds={d} area="Agents > MCP servers" history={d.history} before={before}>
      <p className="px-3 pt-2 text-sm text-text-muted">{lastDays(days)}.</p>
      <table aria-label={label} className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-text-secondary">
            <th className={TH}>Tool</th>
            <th className={TH}>Type</th>
            <th className={TH}>Status</th>
            <th className={`${TH} text-right`}>People</th>
            <th className={`${TH} text-right`}>Devices</th>
            <th className={`${TH} text-right`}>Calls</th>
            <th className={`${TH} text-right`}>Failed</th>
            <th className={TH}>First seen</th>
            <th className={TH}>Last seen</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <ToolRow key={`${t.mcp ? "m" : "b"}:${t.tool}`} t={t} now={now} />
          ))}
        </tbody>
      </table>
    </DrillScope>
  );
}

/** How many built-in tools were called, for the group row; null until known. Asked only
 * where the row shows. */
export function useBuiltInCount(days: number, enabled: boolean): number | null {
  const q = useQuery({
    queryKey: ["agents-overview", days],
    queryFn: () => api.agentsOverview(days),
    refetchInterval: 300_000,
    enabled,
  });
  return q.data ? q.data.tools.filter((t) => !t.mcp).length : null;
}

function Box({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section aria-label={label} className="rounded-card border border-border bg-surface">
      {children}
    </section>
  );
}

function Overview({ d }: { d: AgentsOverview }) {
  return (
    <Box label="Overview">
      <div className="grid grid-cols-2 gap-px bg-border lg:grid-cols-3 min-[1400px]:grid-cols-6">
        <Kpi label="Sessions" kpi={d.sessions} noun="sessions" about={COUNTED.sessions} />
        <Kpi label="People" kpi={d.people} noun="people" about={COUNTED.agentPeople} />
        <Kpi label="Tool calls" kpi={d.calls} noun="tool calls" about={COUNTED.toolCalls} />
        <Kpi
          label="Failed tool calls"
          kpi={d.failed}
          noun="failed calls"
          about={COUNTED.failedCalls}
        />
        <Kpi
          label="Not-approved MCP servers in use"
          kpi={d.mcp_not_approved}
          noun="MCP servers"
          about={COUNTED.mcpNotApproved}
        />
        <Kpi
          label="Devices delivering late"
          kpi={d.late_devices}
          about={COUNTED.lateDevices}
          noun="devices"
          context="Records an hour or more late (the plugin's offline queue)"
        />
      </div>
      {d.missing_devices.length ? (
        <p role="note" className="border-t border-border px-3 py-2 text-sm text-text-secondary">
          <span className="text-warn">
            {d.missing_devices.length === 1
              ? "1 device sent before this window and nothing in it:"
              : `${d.missing_devices.length} devices sent before this window and nothing in it:`}
          </span>{" "}
          {d.missing_devices.map((h, i) => (
            <span key={h} className="font-mono">
              {i ? ", " : ""}
              <EntityLink kind="host" value={h} />
            </span>
          ))}
          . The plugin may be removed, or the device off.
        </p>
      ) : null}
    </Box>
  );
}

const TH = "px-3 py-2";
const TD = "px-3 py-1.5";

function ToolRow({ t, now }: { t: AgentTool; now: string }) {
  const drill = useDrill();
  const open = drill(t.drill, `Tool ${t.tool}`);
  const n = t.calls + t.failed;
  return (
    <tr data-row={t.tool} className="border-b border-border last:border-0">
      <td className={`${TD} font-mono`}>
        <button
          type="button"
          data-drill=""
          onClick={open}
          title={`Open ${n.toLocaleString()} events in Logs`}
          className={cn(DRILL, "text-left")}
        >
          {t.tool}
        </button>
      </td>
      <td className={`${TD} text-text-secondary`}>{t.mcp ? "MCP server" : "Built in"}</td>
      <td className={TD}>
        {t.status === "built_in" ? (
          <span className="text-text-muted">Not reviewed</span>
        ) : (
          <StatusBadge status={t.status} />
        )}
      </td>
      <td className={`${TD} text-right font-mono tabular-nums`}>{t.people}</td>
      <td className={`${TD} text-right font-mono tabular-nums`}>{t.devices}</td>
      <td className={`${TD} text-right font-mono tabular-nums`}>{t.calls.toLocaleString()}</td>
      <td
        className={cn(
          `${TD} text-right font-mono tabular-nums`,
          t.failed ? "text-warn" : "text-text-muted",
        )}
      >
        {t.failed.toLocaleString()}
      </td>
      <When at={t.first_seen} now={now} />
      <When at={t.last_seen} now={now} />
    </tr>
  );
}

function When({ at, now }: { at: string | null; now: string }) {
  return (
    <td className={`${TD} whitespace-nowrap`} title={at ? `${stamp(at)} UTC` : undefined}>
      {at ? since(at, now) : ""}
    </td>
  );
}
