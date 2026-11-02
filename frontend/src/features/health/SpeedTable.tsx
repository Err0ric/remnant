import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

const SLOW_MS = 2000;

function ms(v: number): string {
  return v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`;
}

/** Health > Speed: p50 and p95 per page route over the last 24 hours, from each request's
 * Server-Timing (owner's batch, item 5). Slowest p95 first. Administrators only. */
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
