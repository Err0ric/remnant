import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api, type AgentsOverview, type AgentTool, type PageWindow } from "@/lib/api";
import { cn } from "@/lib/cn";
import { navigate } from "@/lib/route";
import { EntityLink } from "@/components/EntityLink";
import { LoadFailed } from "@/components/LoadFailed";
import { DrillScope, DRILL, Kpi, useDrill } from "@/features/dashboard/Sections";
import { compareLine } from "@/features/dashboard/History";
import { WINDOWS, previousPhrase } from "@/features/dashboard/pageWindow";
import { since, stamp } from "@/features/overview/time";
import { StatusBadge } from "./StatusBadge";

const KEY = "agents.window";
const DAYS: Record<PageWindow, number> = { "24h": 1, "7d": 7, "30d": 30 };

function readWindow(): PageWindow {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "24h" || v === "7d" || v === "30d" ? v : "7d";
  } catch {
    return "7d";
  }
}

/** Agents > Overview and Tools (ADR-0038 section 6): one window for both tabs, from the
 * hooks plugin. Every number opens its rows in Search (ADR-0039). */
export function AgentsArea({ tab }: { tab: "overview" | "tools" }) {
  const [win, setWin] = useState<PageWindow>(readWindow);
  const q = useQuery({
    queryKey: ["agents-overview", win],
    queryFn: () => api.agentsOverview(DAYS[win]),
    refetchInterval: 300_000,
  });
  const pick = (w: PageWindow) => {
    setWin(w);
    try {
      window.localStorage.setItem(KEY, w);
    } catch {
      // Storage blocked: the window still applies for this page view.
    }
  };
  const d = q.data;
  const label = tab === "tools" ? "Tools" : "Overview";
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Time window" className="flex rounded border border-border">
          {WINDOWS.map((w) => (
            <button
              key={w.id}
              type="button"
              aria-pressed={w.id === win}
              onClick={() => pick(w.id)}
              className={cn(
                "h-8 px-3 text-sm first:rounded-l last:rounded-r",
                w.id === win
                  ? "bg-surface-head font-semibold text-text"
                  : "text-text-secondary hover:text-text",
              )}
            >
              {w.label}
            </button>
          ))}
        </div>
        {d?.has_source ? (
          <span className="text-sm text-text-muted">
            {compareLine(d.history.compared, d.history.since, previousPhrase(win))}
          </span>
        ) : null}
      </div>
      {q.isLoading ? (
        <div aria-busy="true" className="h-48 animate-pulse rounded-card bg-surface" />
      ) : q.isError && !d ? (
        <section aria-label={label} className="rounded-card border border-border bg-surface">
          <LoadFailed
            what={`Agents ${label.toLowerCase()}`}
            error={q.error}
            onRetry={() => void q.refetch()}
            retrying={q.isFetching}
          />
        </section>
      ) : !d ? null : !d.has_source ? (
        <section
          aria-label={label}
          className="rounded-card border border-border bg-surface p-5 text-sm"
        >
          <p className="mb-2 font-semibold">Needs the hooks plugin</p>
          <p className="text-text-secondary">
            Install the Claude Code hooks plugin on the devices to see sessions, tool calls, and MCP
            servers here. If a hooks source exists, you may not have access to it.{" "}
            <button
              type="button"
              onClick={() => navigate("plugins")}
              className="text-accent-text hover:underline"
            >
              Get the plugin
            </button>
          </p>
        </section>
      ) : (
        <DrillScope
          bounds={d}
          area={`Agents > ${label}`}
          history={d.history}
          before={previousPhrase(win)}
        >
          {tab === "tools" ? <Tools d={d} /> : <Overview d={d} />}
        </DrillScope>
      )}
    </div>
  );
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
        <Kpi label="Sessions" kpi={d.sessions} noun="sessions" />
        <Kpi label="People" kpi={d.people} noun="people" />
        <Kpi label="Tool calls" kpi={d.calls} noun="tool calls" />
        <Kpi label="Failed tool calls" kpi={d.failed} noun="failed calls" />
        <Kpi label="Not-approved MCP servers in use" kpi={d.mcp_not_approved} noun="MCP servers" />
        <Kpi
          label="Devices delivering late"
          kpi={d.late_devices}
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

const TH = "px-3 py-2 font-semibold";
const TD = "px-3 py-1.5";

function Tools({ d }: { d: AgentsOverview }) {
  const now = new Date().toISOString();
  return (
    <Box label="Tools">
      <div className="flex flex-wrap items-baseline gap-x-3 border-b border-border bg-surface-head px-3 py-2">
        <h2 className="text-base font-semibold">Tools</h2>
        <span className="text-sm text-text-muted">
          Built-in tools and MCP servers Claude Code called. Review MCP servers on the MCP servers
          tab.
        </span>
      </div>
      {d.tools.length === 0 ? (
        <p className="px-3 py-4 text-sm text-text-secondary">No tool calls in this window.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
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
              {d.tools.map((t) => (
                <ToolRow key={`${t.mcp ? "m" : "b"}:${t.tool}`} t={t} now={now} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Box>
  );
}

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
          title={`Open ${n.toLocaleString()} events in Search`}
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
