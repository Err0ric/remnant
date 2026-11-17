import { Skeleton } from "@/components/Skeleton";
import { When } from "@/components/When";
import { EmptyState } from "@/components/EmptyState";
import { useQuery } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";
import { Card } from "@/components/Card";
import { StateNotice } from "@/components/StateNotice";
import { NAMES_HIDDEN } from "@/features/alerts/kinds";
import { EntityList } from "@/components/EntityLink";

const STATE: Record<string, { label: string; tint: string }> = {
  changed: { label: "Changed", tint: "border border-warn text-warn" },
  // Neutral and outlined: the accent is for links and selection only (DESIGN.md 1).
  new: { label: "New agent", tint: "border border-border-strong text-text-secondary" },
  usual: { label: "As usual", tint: "bg-info-bg text-info-tx" },
};

/** AI agents and what changed in the last 24 hours against the 30 days before
 * (ADR-0020 rows 2 and 3). */
export function AgentsCard() {
  const q = useQuery({ queryKey: ["ai-agents"], queryFn: api.aiAgents, staleTime: 60_000 });
  const rows = q.data ?? [];
  const changed = rows.filter((a) => a.state === "changed").length;
  const masked = rows.some((a) => a.masked);
  return (
    <Card
      title="Agents"
      note="Changes are against the 30 days before the last 24 hours."
      badge={
        changed ? (
          <span className="rounded-badge border border-warn px-2 py-0.5 text-sm text-warn">
            {changed} changed
          </span>
        ) : null
      }
    >
      {masked ? (
        <div className="border-b border-border p-2">
          <StateNotice>{NAMES_HIDDEN}</StateNotice>
        </div>
      ) : null}
      {q.error ? (
        <p role="alert" className="px-3 py-4 text-sm text-danger">
          {q.error instanceof ApiError ? q.error.message : "Could not load agents"}
        </p>
      ) : q.isLoading ? (
        <Skeleton label="agents" rows={4} header tall className="rounded-none border-0" />
      ) : rows.length === 0 ? (
        <EmptyState
          kind="not-set-up"
          title="No agents in the last 30 days."
          detail="Claude Code telemetry, the MCP inventory, and the Anthropic usage connector feed this view."
        />
      ) : (
        <div className="overflow-x-auto">
          <table aria-label="Agents" className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-secondary">
                <th className="px-3 py-2">Agent</th>
                <th className="px-3 py-2">Owner</th>
                <th className="px-3 py-2 text-right">Events (24 h)</th>
                <th className="px-3 py-2">Last seen</th>
                <th className="px-3 py-2">What changed</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => {
                const st = STATE[a.state] ?? STATE.usual!;
                return (
                  <tr key={a.agent} className="border-b border-border align-top last:border-0">
                    <td className="px-3 py-2">
                      <div className="font-mono">{a.label}</div>
                      <div className="text-text-muted">{a.kind}</div>
                      {a.machines.length > 1 ? (
                        // Each machine with its own activity (owner, 2026-11-03; D185).
                        <ul aria-label={`Machines for ${a.label}`} className="mt-1">
                          {a.machines.map((m) => (
                            <li key={m.name} className="text-text-secondary">
                              <span className="font-mono text-text">{m.name}</span>: last seen{" "}
                              <When iso={m.last_seen} />, {m.events_24h.toLocaleString()} in 24 h
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 font-mono text-text-secondary">
                      {a.masked && (a.owners_hidden ?? 0) > 0 ? (
                        "Hidden"
                      ) : (
                        <EntityList people={a.owners} tab="ai" />
                      )}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {a.events_24h.toLocaleString()}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2">
                      <When iso={a.last_seen} />
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`rounded-badge px-1.5 py-px text-xs font-semibold ${st.tint}`}
                      >
                        {st.label}
                      </span>
                      {a.new_items.length ? (
                        <ul className="mt-1">
                          {a.new_items.map((i) => (
                            <li key={`${i.kind}:${i.name}`} className="text-text-secondary">
                              New {i.kind}: <span className="font-mono text-text">{i.name}</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {a.recent_peak !== null ? (
                        <div className="mt-1 text-text-secondary">
                          {a.recent_peak} events in one hour (usual busiest {a.usual_peak})
                        </div>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
