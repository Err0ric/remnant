import { useState } from "react";
import type { Overview } from "@/lib/api";
import { navigate } from "@/lib/route";
import { hourSql, seedSearch } from "@/lib/searchSeed";
import { HourCells } from "./HourCells";
import { Panel } from "./Panel";

interface VolumePanelProps {
  overview: Overview;
}

/** Hour axis under the bars: a tick every 3 hours, the date at midnight and at the start. */
function HourAxis({ hours }: { hours: string[] }) {
  return (
    <div
      aria-hidden
      className="grid min-w-[240px] gap-[2px] text-xs text-text-muted"
      style={{ gridTemplateColumns: `repeat(${Math.max(1, hours.length)}, minmax(0, 1fr))` }}
    >
      {hours.map((iso, i) => {
        const d = new Date(iso);
        const h = d.getUTCHours();
        const mark = i === 0 || (h % 3 === 0 && i >= 3); // no tick crowding the first label
        const dated = i === 0 || h === 0;
        return (
          <div key={iso} className="relative h-4">
            {mark ? (
              <span
                className={`absolute left-0 top-0 whitespace-nowrap border-l border-border pl-1 font-mono tabular-nums ${
                  // On a phone, every 6 hours only, so labels do not overlap (QA F16).
                  i !== 0 && (h % 6 !== 0 || i < 6) ? "max-sm:hidden" : ""
                }`}
              >
                {dated
                  ? d.toLocaleString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }) +
                    " "
                  : ""}
                {String(h).padStart(2, "0")}:00
              </span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function unusual(marks: string[]): string {
  const busy = marks.filter((m) => m === "busy").length;
  const quiet = marks.filter((m) => m === "quiet").length;
  return [busy ? `${busy} busy` : "", quiet ? `${quiet} quiet` : ""].filter(Boolean).join(", ");
}

/** Events per readable source per hour over the last 24 hours, as a heatmap. Hours far
 * from the same hour on earlier days are marked (D65) and those sources listed first. */
export function VolumePanel({ overview }: VolumePanelProps) {
  const [hover, setHover] = useState<{ row: string; hour: number } | null>(null);
  const rows = overview.volume
    .map((v) => ({
      ...v,
      total: v.counts.reduce((a, b) => a + b, 0),
      flagged: v.marks.filter(Boolean).length,
    }))
    .sort((a, b) => b.flagged - a.flagged || b.total - a.total);
  const open = (source: string, hour: number) => {
    const sql = hourSql(source, overview.hours[hour] ?? "");
    if (!sql) return;
    seedSearch({ sql });
    navigate("search");
  };
  const total = rows.reduce((a, r) => a + r.total, 0);
  const hours = overview.hours;
  return (
    <Panel title="Event volume" meta={`${total.toLocaleString()} events · last 24 hours`} wide>
      {rows.length === 0 ? (
        <p className="text-text-secondary">
          No events timed in the last 24 hours from the sources you can read.
        </p>
      ) : (
        <div className="overflow-x-auto pt-4">
          <table aria-label="Events per source per hour" className="w-full">
            <thead>
              <tr className="text-left text-text-secondary">
                <th className="py-1 pr-3 font-semibold">Source</th>
                <th className="py-1 pr-3 text-right font-semibold">Events</th>
                <th className="py-1 pr-3 font-semibold">Unusual</th>
                <th className="py-1 font-semibold">Per hour (UTC)</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.source_id} className="border-t border-border">
                  <td className="py-1 pr-3 font-mono">{r.source_id}</td>
                  <td className="py-1 pr-3 text-right font-mono tabular-nums">
                    {r.total.toLocaleString()}
                  </td>
                  <td className="whitespace-nowrap py-1 pr-3 text-warn">{unusual(r.marks)}</td>
                  <td className="w-full py-1">
                    <HourCells
                      source={r.source_id}
                      counts={r.counts}
                      hours={hours}
                      typical={r.typical}
                      marks={r.marks}
                      active={hover?.hour ?? null}
                      onActive={(hour) =>
                        setHover(hour === null ? null : { row: r.source_id, hour })
                      }
                      showTip={hover?.row === r.source_id}
                      onOpen={(hour) => open(r.source_id, hour)}
                    />
                  </td>
                </tr>
              ))}
              <tr>
                <td />
                <td />
                <td />
                <td className="pt-1">
                  <HourAxis hours={hours} />
                </td>
              </tr>
            </tbody>
          </table>
          <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-text-secondary">
            <span>Stronger shading means more events for that source.</span>
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="inline-block h-3 w-4 rounded-sm bg-inset ring-2 ring-inset ring-warn"
              />
              Busier than usual
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="hatch inline-block h-3 w-4 rounded-sm bg-inset" />
              Much quieter than usual
            </span>
            <span>
              Compared with the same hour on the 7 days before. Select a cell to search it.
            </span>
          </p>
        </div>
      )}
    </Panel>
  );
}
