import { useQuery } from "@tanstack/react-query";
import { LoadFailed } from "@/components/LoadFailed";
import { EntityLink } from "@/components/EntityLink";
import { api, type Cell } from "@/lib/api";
import { cn } from "@/lib/cn";
import { openDrill } from "@/lib/drill";
import { formatCell } from "@/lib/search";

const SHOWN = [
  "time",
  "source_id",
  "actor_user_name",
  "device_hostname",
  "src_endpoint_ip",
  "message",
] as const;
const LABEL: Record<(typeof SHOWN)[number], string> = {
  time: "Time (UTC)",
  source_id: "Source",
  actor_user_name: "Person",
  device_hostname: "Device",
  src_endpoint_ip: "Address",
  message: "Message",
};
const KIND = {
  actor_user_name: "user",
  device_hostname: "host",
  src_endpoint_ip: "ip",
} as const;

function clock(v: Cell): string {
  return typeof v === "string" ? v.slice(11, 19) : formatCell(v);
}

/** Around this event (ADR-0038 section 8): 5 minutes either side, same person or same
 * device, every source the viewer may read, newest last. Likely cause is a hint in the
 * accent tint, never a severity color, with the rule that picked it in its tooltip. */
export function AroundEvent({ eventId, at }: { eventId: string; at: string }) {
  const q = useQuery({
    queryKey: ["around", eventId, at],
    queryFn: () => api.eventAround(eventId, at),
  });
  const d = q.data;
  return (
    <section
      aria-label="Around this event"
      className="mb-3 overflow-hidden rounded border border-border bg-surface"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border bg-surface-head px-3 py-1.5">
        <h3 className="text-sm font-semibold">Around this event</h3>
        {d ? (
          <span className="text-sm text-text-muted">
            5 minutes either side
            {d.person.length ? `, ${d.person.join(", ")}` : ""}
            {d.devices.length ? `, ${d.devices.join(", ")}` : ""}
            {d.joined_by_address ? " (the person who held the address then)" : ""}
            {d.more ? ". The 50 rows nearest in time" : ""}
          </span>
        ) : null}
        {d ? (
          <button
            type="button"
            onClick={() =>
              openDrill({ sql: d.sql, from: d.start, to: d.end, origin: "Around this event" })
            }
            className="ml-auto text-sm text-accent-text hover:underline"
          >
            Open in Search
          </button>
        ) : null}
      </div>
      {q.isLoading ? (
        <div aria-busy="true" className="h-24 animate-pulse" />
      ) : q.isError ? (
        <LoadFailed
          what="the rows around this event"
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
        />
      ) : d ? (
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr className="border-b border-border text-left text-text-secondary">
                <th className="px-3 py-1.5 font-semibold">
                  <span className="sr-only">Mark</span>
                </th>
                {SHOWN.map((c) => (
                  <th key={c} className="px-3 py-1.5 font-semibold">
                    {LABEL[c]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r) => {
                const id = String(r[d.columns.indexOf("event_id")] ?? "");
                const self = id === eventId;
                const cause = id === d.likely_cause;
                return (
                  <tr
                    key={id}
                    data-row={id}
                    className={cn(
                      "border-b border-border last:border-0",
                      self && "bg-row-selected",
                      cause && "bg-accent-subtle",
                    )}
                  >
                    <td className="whitespace-nowrap px-3 py-1">
                      {self ? (
                        <span className="text-xs font-semibold">This event</span>
                      ) : cause ? (
                        <span
                          title={`Likely cause: ${d.likely_rule}`}
                          className="text-xs font-semibold text-accent-text"
                        >
                          Likely cause
                        </span>
                      ) : null}
                    </td>
                    {SHOWN.map((c) => {
                      const v = r[d.columns.indexOf(c)] ?? null;
                      const kind = c in KIND ? KIND[c as keyof typeof KIND] : null;
                      return (
                        <td
                          key={c}
                          className={cn(
                            "px-3 py-1",
                            c === "message" ? "max-w-md truncate" : "whitespace-nowrap font-mono",
                          )}
                          title={c === "message" ? formatCell(v) : undefined}
                        >
                          {c === "time" ? (
                            clock(v)
                          ) : kind && v ? (
                            <EntityLink kind={kind} value={v} label={formatCell(v)} />
                          ) : (
                            formatCell(v)
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
