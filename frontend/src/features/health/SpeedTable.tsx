import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

const SLOW_MS = 2000;

function ms(v: number): string {
  return v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`;
}

/** Health > Speed: p50 and p95 per page route over the last 24 hours, from each request's
 * Server-Timing (owner's batch, item 5). Slowest p95 first. Administrators only. */
/** Background refreshes of the default views (D147): one count per hour, last 24 hours. */
function Refreshes() {
  const q = useQuery({ queryKey: ["health", "refreshes"], queryFn: api.healthRefreshes });
  const data = q.data;
  if (!data || !Array.isArray(data.hours)) return null;
  const total = data.hours.reduce((n, h) => n + h.refreshes, 0);
  const failed = data.hours.reduce((n, h) => n + h.failed, 0);
  const top = Math.max(1, ...data.hours.map((h) => h.refreshes + h.failed));
  return (
    <div className="border-b border-border px-3 py-2 text-sm">
      <p className="text-text-secondary">
        Background refreshes (7-day Dashboard, Microsoft 365 Overview, AI Watch):{" "}
        <span className="font-mono tabular-nums text-text-primary">{total}</span> in 24 hours
        {failed ? (
          <>
            , <span className="font-mono tabular-nums text-sev-medium-text">{failed}</span> failed
          </>
        ) : null}
        . <span className="font-mono tabular-nums text-text-primary">{data.views}</span>{" "}
        {data.views === 1 ? "view" : "views"} kept fresh now; a view stops 10 minutes after its last
        load.
      </p>
      <ol aria-label="Refreshes per hour" className="mt-2 flex h-8 items-end gap-px">
        {data.hours.map((h) => {
          const n = h.refreshes + h.failed;
          const label = `${new Date(h.hour).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}: ${h.refreshes} refreshes${h.failed ? `, ${h.failed} failed` : ""}`;
          return (
            <li
              key={h.hour}
              title={label}
              aria-label={label}
              className={`flex-1 ${h.failed ? "bg-sev-medium-text" : "bg-accent"}`}
              style={{ height: n ? `${Math.max(8, (100 * n) / top)}%` : "1px" }}
            />
          );
        })}
      </ol>
    </div>
  );
}

export function SpeedTable() {
  const q = useQuery({ queryKey: ["health", "speed"], queryFn: api.healthSpeed });
  if (q.error) {
    return (
      <p role="alert" className="px-3 py-2 text-sm text-danger">
        {q.error instanceof ApiError ? q.error.message : "Could not load page speed"}
      </p>
    );
  }
  const rows = q.data ?? [];
  return (
    <section aria-label="Speed" className="rounded-card border border-border bg-surface">
      <p className="border-b border-border px-3 py-2 text-sm text-text-secondary">
        Pages that read data, over the last 24 hours or since the server started. Wait is time
        queued for a query slot; DuckDB is time reading data.
      </p>
      <Refreshes />
      {q.isLoading ? (
        <p className="px-3 py-2 text-sm text-text-muted">Loading</p>
      ) : rows.length === 0 ? (
        <p className="px-3 py-2 text-sm text-text-muted">No page loads recorded yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" aria-label="Page speed by route">
            <thead>
              <tr className="border-b border-border text-left text-text-secondary">
                <th className="px-3 py-2 font-semibold">Route</th>
                <th className="px-3 py-2 text-right font-semibold">Requests</th>
                <th className="px-3 py-2 text-right font-semibold">p50</th>
                <th className="px-3 py-2 text-right font-semibold">p95</th>
                <th className="hidden px-3 py-2 text-right font-semibold md:table-cell">
                  DuckDB p50
                </th>
                <th className="hidden px-3 py-2 text-right font-semibold md:table-cell">
                  Wait p95
                </th>
                <th className="hidden px-3 py-2 text-right font-semibold md:table-cell">
                  From cache
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.route} className="border-b border-border last:border-b-0">
                  <td className="break-all px-3 py-2 font-mono">{r.route}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">{r.requests}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">{ms(r.p50_ms)}</td>
                  <td
                    className={`px-3 py-2 text-right font-mono tabular-nums ${
                      r.p95_ms >= SLOW_MS ? "font-semibold text-sev-medium-text" : ""
                    }`}
                  >
                    {ms(r.p95_ms)}
                  </td>
                  <td className="hidden px-3 py-2 text-right font-mono tabular-nums md:table-cell">
                    {ms(r.db_p50_ms)}
                  </td>
                  <td className="hidden px-3 py-2 text-right font-mono tabular-nums md:table-cell">
                    {ms(r.wait_p95_ms)}
                  </td>
                  <td className="hidden px-3 py-2 text-right font-mono tabular-nums md:table-cell">
                    {r.cached ? `${Math.round((100 * r.cache_hits) / r.cached)}%` : "·"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
