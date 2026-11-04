import { useQuery } from "@tanstack/react-query";
import { EntityLink } from "@/components/EntityLink";
import { LoadFailed } from "@/components/LoadFailed";
import { When } from "@/components/When";
import { api, type PersonUsed } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Box } from "./PersonLists";

const TH = "px-3 py-2 font-semibold";
const TD = "px-3 py-1.5";

function UsedTable({
  label,
  kind,
  rows,
}: {
  label: string;
  kind: "host" | "ip";
  rows: PersonUsed[];
}) {
  if (!rows.length)
    return <p className="px-3 py-3 text-sm text-text-secondary">None in this range.</p>;
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-text-secondary">
            <th className={TH}>{kind === "host" ? "Host" : "Address"}</th>
            <th className={`${TH} text-right`}>Events</th>
            <th className={`${TH} text-right`}>Failed sign-ins</th>
            <th className={TH}>Last seen</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.value} className="border-b border-border last:border-0">
              <td className={`${TD} font-mono`}>
                <EntityLink kind={kind} value={r.value} />
              </td>
              <td className={`${TD} text-right font-mono tabular-nums`}>
                {r.events.toLocaleString()}
              </td>
              <td
                className={cn(
                  `${TD} text-right font-mono tabular-nums`,
                  r.failed ? "text-warn" : "text-text-muted",
                )}
              >
                {r.failed.toLocaleString()}
              </td>
              <td className={TD}>{r.last_seen ? <When iso={r.last_seen} /> : "·"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The hosts and addresses on a person's own records (D197), each opening its own page. */
export function PersonHosts({ person, days }: { person: string; days: number }) {
  const q = useQuery({
    queryKey: ["person-hosts", person, days],
    queryFn: () => api.personHosts(person, days),
  });
  if (q.isLoading) return <div aria-busy="true" className="h-40 animate-pulse" />;
  if (q.isError || !q.data)
    return (
      <LoadFailed
        what="hosts and devices"
        error={q.error}
        onRetry={() => void q.refetch()}
        retrying={q.isFetching}
      />
    );
  const range = `last ${days} ${days === 1 ? "day" : "days"}`;
  return (
    <div role="region" aria-label="Hosts and devices" className="grid gap-3 lg:grid-cols-2">
      <Box label="Hosts" note={`on this person's records, ${range}`}>
        <UsedTable label="Hosts" kind="host" rows={q.data.hosts} />
      </Box>
      <Box label="Source addresses" note={range}>
        <UsedTable label="Source addresses" kind="ip" rows={q.data.addresses} />
      </Box>
    </div>
  );
}
