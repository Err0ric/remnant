import { useQuery } from "@tanstack/react-query";
import { EntityLink } from "@/components/EntityLink";
import { LoadFailed } from "@/components/LoadFailed";
import { When } from "@/components/When";
import { TierBadge } from "@/features/ai/AccountsCard";
import { api, type PersonAiCount } from "@/lib/api";
import { cn } from "@/lib/cn";
import { navigateTab } from "@/lib/route";
import { Box } from "./PersonLists";

const TH = "px-3 py-2 font-semibold";
const TD = "px-3 py-1.5";

function Counts({
  label,
  rows,
  mono = true,
  empty,
}: {
  label: string;
  rows: PersonAiCount[];
  mono?: boolean;
  empty: string;
}) {
  return (
    <Box label={label}>
      {rows.length ? (
        <ul className="flex flex-col py-1 text-sm">
          {rows.map((r) => (
            <li key={r.name} className="flex gap-3 px-3 py-0.5">
              <span className={cn("min-w-0 flex-1 [overflow-wrap:anywhere]", mono && "font-mono")}>
                {r.name}
              </span>
              <span className="font-mono tabular-nums text-text-secondary">
                {r.n.toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-3 py-3 text-sm text-text-muted">{empty}</p>
      )}
    </Box>
  );
}

/** One person's AI activity (owner, 2026-11-03; D189): flags first, then accounts and
 * devices, AI services on the network, sessions newest first, and rollups for the range.
 * Metadata only: what was touched, never what was said. */
export function PersonAiActivity({ person, days }: { person: string; days: number }) {
  const q = useQuery({
    queryKey: ["person-ai", person, days],
    queryFn: () => api.personAi(person, days),
  });
  if (q.isLoading) return <div aria-busy="true" className="h-40 animate-pulse" />;
  if (q.isError || !q.data)
    return (
      <LoadFailed
        what="AI activity"
        error={q.error}
        onRetry={() => void q.refetch()}
        retrying={q.isFetching}
      />
    );
  const a = q.data;
  const range = `last ${days} ${days === 1 ? "day" : "days"}`;
  return (
    <div aria-label="AI activity" role="region" className="flex flex-col gap-3">
      <Box label="Flags" note={range}>
        {a.flags.length ? (
          <ul className="flex flex-col gap-1 px-3 py-2 text-sm">
            {a.flags.map((f) => (
              <li key={f.kind}>
                <span className="rounded-badge border border-warn px-1.5 text-xs text-warn">
                  {f.text}
                </span>{" "}
                <span className="font-mono tabular-nums">{f.count.toLocaleString()}</span>
                {f.examples.length ? (
                  <span className="font-mono text-text-secondary [overflow-wrap:anywhere]">
                    {": "}
                    {f.examples.join(", ")}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-3 py-3 text-sm text-text-secondary">Nothing flagged in this range.</p>
        )}
      </Box>
      <div className="grid gap-3 lg:grid-cols-2">
        <Box label="Accounts and devices">
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 px-3 py-2 text-sm">
            <dt className="text-text-secondary">Claude accounts</dt>
            <dd>
              {a.accounts.length ? (
                <ul>
                  {a.accounts.map((x) => (
                    <li key={x.email ?? "none"}>
                      <TierBadge tier={x.tier} />{" "}
                      <span className="font-mono">{x.email ?? "No email"}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <span className="text-text-secondary">None reported</span>
              )}
            </dd>
            <dt className="text-text-secondary">Devices</dt>
            <dd className="font-mono">
              {a.devices.length ? (
                a.devices.map((d, i) => (
                  <span key={d}>
                    {i ? ", " : ""}
                    <EntityLink kind="host" value={d} />
                  </span>
                ))
              ) : (
                <span className="font-sans text-text-secondary">None seen</span>
              )}
            </dd>
          </dl>
        </Box>
        <Box label="AI services on the network" note="DNS, firewall, and proxy logs">
          {a.services.length ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-text-secondary">
                  <th className={TH}>Service</th>
                  <th className={`${TH} text-right`}>Lookups</th>
                  <th className={TH}>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {a.services.map((s) => (
                  <tr key={s.service_id} className="border-b border-border last:border-0">
                    <td className={TD}>
                      <EntityLink kind="service" value={s.service_id} label={s.name} />
                    </td>
                    <td className={`${TD} text-right font-mono tabular-nums`}>
                      {s.events.toLocaleString()}
                    </td>
                    <td className={TD}>
                      <When iso={s.last_seen} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="px-3 py-3 text-sm text-text-secondary">
              No AI services seen for this person on the network in this range.
            </p>
          )}
        </Box>
      </div>
      <Box label="Claude Code sessions" note={`newest first, ${range}`}>
        {a.sessions.length ? (
          <ul className="flex flex-col text-sm">
            {a.sessions.map((s) => (
              <li
                key={s.session_id}
                className="grid grid-cols-[9rem_minmax(0,1fr)] gap-x-3 border-b border-border px-3 py-1.5 last:border-0 sm:grid-cols-[9rem_8rem_minmax(0,1fr)]"
              >
                <button
                  type="button"
                  onClick={() =>
                    navigateTab("agents", "sessions", `session=${encodeURIComponent(s.session_id)}`)
                  }
                  className="text-left text-accent-text hover:underline"
                >
                  <When iso={s.started} />
                </button>
                <span className="hidden truncate font-mono text-text-secondary sm:block">
                  {s.machine ?? "·"}
                </span>
                <span className={cn("min-w-0", s.flagged && "text-warn")}>{s.summary}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-3 py-3 text-sm text-text-secondary">
            No Claude Code sessions from the hooks plugin in this range.
          </p>
        )}
      </Box>
      {a.cut ? (
        <p role="note" className="text-sm text-text-muted">
          More activity than one page counts: the rollups cover the earliest records in the range.
        </p>
      ) : null}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <Counts label="Tools used" rows={a.tools} empty="No tool calls" />
        <Counts label="Files written or edited" rows={a.files} empty="No files written" />
        <Counts label="Commands" rows={a.commands} empty="No shell commands" />
        <Counts label="Web domains fetched or searched" rows={a.domains} empty="No web domains" />
        <Counts label="MCP servers" rows={a.mcp} empty="No MCP servers" />
      </div>
    </div>
  );
}
