import { useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

const PAGE = 50;
const MORE = 200;

interface VendorAlertsProps {
  itemId: string;
}

/** An external alert item's vendor alerts (D228): the count and the first 50 IDs, "Show
 * all" a page at a time, and the alerts' own events from a server-built query. */
export function VendorAlerts({ itemId }: VendorAlertsProps) {
  const [events, setEvents] = useState(false);
  const ids = useInfiniteQuery({
    queryKey: ["alerts", "ids", itemId],
    queryFn: ({ pageParam }) => api.alertIds(itemId, pageParam, pageParam ? MORE : PAGE),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const seen = pages.reduce((n, p) => n + p.ids.length, 0);
      return seen < last.count ? seen : undefined;
    },
  });
  const rows = useQuery({
    queryKey: ["alerts", "events", itemId],
    queryFn: () => api.alertEvents(itemId),
    enabled: events,
  });
  if (ids.isLoading) return <div className="h-12 animate-pulse rounded bg-surface-head" />;
  const count = ids.data?.pages[0]?.count ?? 0;
  const list = ids.data?.pages.flatMap((p) => p.ids) ?? [];
  if (!count) return null;
  return (
    <div className="grid gap-2">
      <div className="grid gap-1">
        <h4 className="text-xs font-semibold text-text-secondary">
          Vendor alerts <span className="font-normal tabular-nums">({count.toLocaleString()})</span>
        </h4>
        <ul aria-label="Vendor alert IDs" className="flex flex-wrap gap-1 font-mono text-xs">
          {list.map((i) => (
            <li
              key={`${i.product}|${i.alert_id}`}
              title={i.product}
              className="rounded border border-border px-1 [overflow-wrap:anywhere]"
            >
              {i.alert_id}
            </li>
          ))}
        </ul>
        {ids.hasNextPage ? (
          <button
            type="button"
            onClick={() => void ids.fetchNextPage()}
            disabled={ids.isFetchingNextPage}
            className="justify-self-start text-accent-text hover:underline disabled:opacity-60"
          >
            Show all ({(count - list.length).toLocaleString()} more, {MORE} at a time)
          </button>
        ) : null}
      </div>
      {events ? (
        rows.isLoading ? (
          <div className="h-12 animate-pulse rounded bg-surface-head" />
        ) : rows.data && rows.data.rows.length ? (
          <div className="min-w-0 overflow-x-auto">
            <table aria-label="Alert events" className="w-full text-left font-mono text-xs">
              <thead>
                <tr className="text-text-muted">
                  {rows.data.columns.map((c) => (
                    <th key={c} className="px-2 py-1 font-normal">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.data.rows.map((row, r) => (
                  <tr key={r} className="border-t border-border">
                    {row.map((cell, j) => (
                      <td key={j} className="px-2 py-1 [overflow-wrap:anywhere]">
                        {String(cell ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-text-muted">
            {rows.isError
              ? "The alert events could not be loaded."
              : "No events kept for these alerts."}
          </p>
        )
      ) : (
        <button
          type="button"
          onClick={() => setEvents(true)}
          className="justify-self-start text-accent-text hover:underline"
        >
          Show alert events
        </button>
      )}
    </div>
  );
}
