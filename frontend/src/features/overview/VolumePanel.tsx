import type { Overview } from "@/lib/api";
import { HourBars } from "./HourBars";
import { Panel } from "./Panel";

interface VolumePanelProps {
  overview: Overview;
}

/** Events per readable source per hour over the last 24 hours. */
export function VolumePanel({ overview }: VolumePanelProps) {
  const rows = overview.volume
    .map((v) => ({ ...v, total: v.counts.reduce((a, b) => a + b, 0) }))
    .sort((a, b) => b.total - a.total);
  const total = rows.reduce((a, r) => a + r.total, 0);
  const max = Math.max(0, ...rows.flatMap((r) => r.counts));
  return (
    <Panel title="Event volume" meta={`${total.toLocaleString()} events · last 24 hours`} wide>
      {rows.length === 0 ? (
        <p className="text-text-secondary">
          No events timed in the last 24 hours from the sources you can read.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table aria-label="Events per source per hour" className="w-full">
            <thead>
              <tr className="text-left text-text-secondary">
                <th className="py-1 pr-3 font-semibold">Source</th>
                <th className="py-1 pr-3 text-right font-semibold">Events</th>
                <th className="py-1 font-semibold">Per hour, oldest to newest</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.source_id} className="border-t border-border">
                  <td className="py-1 pr-3 font-mono">{r.source_id}</td>
                  <td className="py-1 pr-3 text-right font-mono tabular-nums">
                    {r.total.toLocaleString()}
                  </td>
                  <td className="w-full py-1">
                    <HourBars
                      counts={r.counts}
                      max={max}
                      label={`${r.source_id}: ${r.total} events in 24 hours, busiest hour ${Math.max(...r.counts)}`}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
