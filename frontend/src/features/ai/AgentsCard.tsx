import { useQuery } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";

const STATE: Record<string, { label: string; tint: string }> = {
  changed: { label: "Changed", tint: "bg-sev-high-bg text-sev-high-text" },
  new: { label: "New agent", tint: "bg-sev-low-bg text-sev-low-text" },
  usual: { label: "As usual", tint: "bg-sev-info-bg text-sev-info-text" },
};

function when(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

/** AI agents and what changed in the last 24 hours against the 30 days before
 * (ADR-0020 rows 2 and 3). */
export function AgentsCard() {
  const q = useQuery({ queryKey: ["ai-agents"], queryFn: api.aiAgents, staleTime: 60_000 });
  const rows = q.data ?? [];
  const changed = rows.filter((a) => a.state === "changed").length;
  return (
    <section
      aria-label="Agents"
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-surface-head px-3 py-2">
        <h2 className="text-base font-semibold">Agents</h2>
        <span className="text-sm text-text-muted">
          Claude Code per person, MCP setups per machine and client, and API keys. Changes are
          against the 30 days before the last 24 hours.
        </span>
        {changed ? (
          <span className="ml-auto rounded-badge bg-sev-high-bg px-2 py-0.5 text-sm text-sev-high-text">
            {changed} changed
          </span>
        ) : null}
      </div>
      {q.error ? (
        <p role="alert" className="px-3 py-4 text-sm text-danger">
          {q.error instanceof ApiError ? q.error.message : "Could not load agents"}
        </p>
      ) : q.isLoading ? (
        <p className="px-3 py-4 text-sm text-text-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="px-3 py-6 text-center text-sm text-text-secondary">
          No agents in the last 30 days. Claude Code telemetry, the MCP inventory, and the Anthropic
          usage connector feed this view.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table aria-label="Agents" className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-secondary">
                <th className="px-3 py-2 font-semibold">Agent</th>
                <th className="px-3 py-2 font-semibold">Owner</th>
                <th className="px-3 py-2 text-right font-semibold">Events (24 h)</th>
                <th className="px-3 py-2 font-semibold">Last seen (UTC)</th>
                <th className="px-3 py-2 font-semibold">What changed</th>
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
                    </td>
                    <td className="px-3 py-2 font-mono text-text-secondary">
                      {a.owners.join(", ") || "·"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums">
                      {a.events_24h.toLocaleString()}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 font-mono">{when(a.last_seen)}</td>
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
    </section>
  );
}
