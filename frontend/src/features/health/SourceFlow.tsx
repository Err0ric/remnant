import { useEffect } from "react";
import { When } from "@/components/When";
import type { Overview, SourceGap } from "@/lib/api";
import { cn } from "@/lib/cn";
import { stamp } from "@/features/overview/time";
import { gapText, lag, localHour, shownGaps, zoneName } from "./flow";
import { SourceStatusLabel } from "./SourceStatusLabel";
import { greyedStatus } from "./sourceStatus";
import { timesNote } from "@/lib/localTime";

export type FlowLevel = "unhealthy" | "attention" | "paused" | "healthy";

export interface FlowSource {
  source_id: string;
  level: FlowLevel;
  word?: string;
  reason?: string | null;
  /** The reason is only the quiet sentence ("No events for over 1 h"). */
  quietNote?: boolean;
  last: string | null;
  onOpen?: () => void;
}

interface SourceFlowProps {
  overview: Overview | undefined;
  sources: FlowSource[];
  now: string;
  /** A problem with stored data as a whole (damaged files moved aside). */
  notice?: string | null;
  /** For tests; the viewer's own zone otherwise. */
  timeZone?: string;
  /** The source a link opened (`/health#source=<id>`): marked and scrolled into view. */
  focused?: string | null;
}

const WORD: Record<FlowLevel, string> = {
  unhealthy: "Unhealthy",
  attention: "Needs attention",
  paused: "Paused",
  healthy: "Flowing",
};
// Source, Status, the line, Peak, 24 hours, Per minute, Last received (D255).
const COLS =
  "grid grid-cols-1 gap-x-4 gap-y-1 md:grid-cols-[minmax(8rem,12rem)_minmax(6rem,9rem)_minmax(6rem,1fr)_3.5rem_4.5rem_4.5rem_9rem] min-[1400px]:grid-cols-[minmax(8rem,12rem)_minmax(6rem,9rem)_minmax(6rem,1fr)_3.5rem_4.5rem_4.5rem_14rem]";

function compact(n: number): string {
  if (n < 1000) return n.toLocaleString();
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

interface SparkProps {
  counts: number[];
  hours: string[];
  gaps: SourceGap[];
  name: string;
  timeZone?: string;
  /** Only quiet: the line in the neutral series color. */
  quiet?: boolean;
}

/** Events per hour as a line, gap hours shaded (F55); the peak is its own column. The
 * reading for each hour is in a tooltip; the totals beside it are printed. */
function Spark({ counts, hours, gaps, name, timeZone, quiet = false }: SparkProps) {
  const n = Math.max(1, counts.length);
  const peak = Math.max(0, ...counts);
  const top = Math.max(1, peak);
  const x = (i: number) => (i / (n - 1 || 1)) * 100;
  const y = (v: number) => 26 - (v / top) * 22;
  const line = counts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(v).toFixed(2)}`);
  const inGap = (i: number) =>
    gaps.some((g) => {
      const start = hours.indexOf(g.start);
      return start >= 0 && i >= start && i < start + g.hours;
    });
  if (!peak)
    return (
      <div
        role="img"
        aria-label={`${name}: no events in 24 hours`}
        className="h-8 min-w-0 border-b border-dashed border-border-strong"
      />
    );
  return (
    <div className="h-8 min-w-0">
      <svg
        viewBox="0 0 100 28"
        preserveAspectRatio="none"
        className="block h-8 w-full"
        role="img"
        aria-label={`${name}: events per hour over 24 hours, peak ${peak.toLocaleString()} an hour`}
      >
        {counts.map((_, i) =>
          inGap(i) ? (
            <rect
              key={`g${i}`}
              x={x(i) - 50 / (n - 1)}
              width={100 / (n - 1)}
              y={0}
              height={28}
              className="fill-danger opacity-15"
            />
          ) : null,
        )}
        <path
          d={line.join(" ")}
          className={quiet ? "fill-none stroke-series-neutral" : "fill-none stroke-accent-text"}
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
        {counts.map((v, i) => (
          <rect
            key={`h${i}`}
            x={x(i) - 50 / (n - 1)}
            width={100 / (n - 1)}
            y={0}
            height={28}
            className="fill-transparent"
          >
            <title>{`${localHour(hours[i] ?? "", timeZone)} (${stamp(hours[i] ?? "").slice(11)} UTC): ${v.toLocaleString()} events`}</title>
          </rect>
        ))}
      </svg>
    </div>
  );
}

/** Health > Sources (F55): one row per source, flow over 24 hours, totals, current rate,
 * and lag, with gaps written out under the row. */
export function SourceFlow({
  overview,
  sources,
  now,
  notice,
  timeZone,
  focused = null,
}: SourceFlowProps) {
  useEffect(() => {
    if (focused) document.getElementById(`flow-${focused}`)?.scrollIntoView?.({ block: "center" });
  }, [focused, sources.length]);
  const hours = overview?.hours ?? [];
  const volume = new Map((overview?.volume ?? []).map((v) => [v.source_id, v]));
  const health = new Map((overview?.sources ?? []).map((s) => [s.source_id, s]));
  const zone = zoneName(timeZone);
  const ticks = hours
    .map((h, i) => ({ h, i }))
    .filter(({ i }) => i % 6 === 0 || i === hours.length - 1);
  return (
    <div className="text-sm">
      {notice ? (
        <p role="status" className="border-b border-border px-3 py-2 text-warn">
          Data folder: {notice}
        </p>
      ) : null}
      <div
        className={`${COLS} border-b border-border px-3 py-2 text-xs font-medium text-text-secondary max-md:hidden`}
      >
        <span>Source</span>
        <span>Status</span>
        <span className="relative h-4 min-w-0" aria-label={`Hour axis, ${zone}`}>
          {ticks.map(({ h, i }) => (
            <span
              key={h}
              title={`${stamp(h)} UTC`}
              className="absolute top-0 whitespace-nowrap font-mono text-xs tabular-nums text-text-muted"
              style={{
                left: `${(i / Math.max(1, hours.length - 1)) * 100}%`,
                transform:
                  i === 0
                    ? "none"
                    : i === hours.length - 1
                      ? "translateX(-100%)"
                      : "translateX(-50%)",
              }}
            >
              {i === hours.length - 1 ? "now" : localHour(h, timeZone)}
            </span>
          ))}
        </span>
        <span className="text-right">Peak</span>
        <span className="text-right">24 hours</span>
        <span className="text-right">Per minute</span>
        <span className="text-right">Last received</span>
      </div>
      <ul aria-label="Sources">
        {sources.map((s) => {
          const v = volume.get(s.source_id);
          const h = health.get(s.source_id);
          const counts = v?.counts ?? hours.map(() => 0);
          // Inside its "Quiet is normal" days no gap is drawn or said (D260).
          const gaps = shownGaps(h, v?.gaps);
          const last = h?.last_event_at ?? s.last;
          const ago = lag(last, now);
          const peak = Math.max(0, ...counts);
          // Only quiet (no gap hours in the 24 hours, not in error) is drawn greyed with one
          // sentence; a gap keeps its danger shading and sentence (D255). Drawing only: the
          // level and the counts stay the server's. Every quiet source has a gap alert open,
          // so the gap hours, not the alert, tell a real gap from a source that is only quiet.
          // An idle source is drawn the same way, though it counts as healthy (D260).
          const gapped = gaps.length > 0;
          // A reader stopped on an error ("Unhealthy" before the Overview says so) is drawn
          // red, never greyed.
          const quiet = s.word !== "Unhealthy" && greyedStatus(h, v?.gaps);
          const num = cn("font-mono tabular-nums md:text-right", quiet && "text-text-secondary");
          return (
            <li
              key={s.source_id}
              id={`flow-${s.source_id}`}
              data-quiet={quiet ? "" : undefined}
              aria-current={focused === s.source_id ? "true" : undefined}
              className={`border-b border-border px-3 py-1.5 last:border-0 ${focused === s.source_id ? "bg-accent-subtle" : ""}`}
            >
              <div className={`${COLS} items-center`}>
                <div className="min-w-0">
                  {s.onOpen ? (
                    <button
                      type="button"
                      onClick={s.onOpen}
                      className={cn(
                        "text-left font-mono [overflow-wrap:anywhere] hover:underline",
                        quiet ? "text-text-secondary" : "text-accent-text",
                      )}
                    >
                      {s.source_id}
                    </button>
                  ) : (
                    <span
                      className={cn(
                        "font-mono [overflow-wrap:anywhere]",
                        quiet && "text-text-secondary",
                      )}
                    >
                      {s.source_id}
                    </span>
                  )}
                </div>
                <SourceStatusLabel level={s.level} word={s.word ?? WORD[s.level]} greyed={quiet} />
                <Spark
                  counts={counts}
                  hours={hours}
                  gaps={gaps}
                  name={s.source_id}
                  timeZone={timeZone}
                  quiet={quiet}
                />
                <span data-peak="" className={num}>
                  {compact(peak)}/h
                  <span className="text-text-muted md:hidden"> at the busiest hour</span>
                </span>
                <span className={num}>
                  {(v?.total ?? 0).toLocaleString()}
                  <span className="text-text-muted md:hidden"> events in 24 h</span>
                </span>
                <span className={num}>
                  {(h?.rate_per_min ?? 0).toLocaleString()}
                  <span className="text-text-muted md:hidden"> per minute</span>
                </span>
                <span className={cn(num, "whitespace-nowrap")}>
                  {last ? (
                    <>
                      <When iso={last} timeZone={timeZone} />
                      {ago ? (
                        <span className="hidden text-text-muted min-[1400px]:inline">
                          {" "}
                          {ago} ago
                        </span>
                      ) : null}
                    </>
                  ) : (
                    "never"
                  )}
                </span>
              </div>
              {gaps.map((g) => (
                <p key={g.start} className="mt-1 text-danger" title={`From ${stamp(g.start)} UTC`}>
                  {gapText(g, now, timeZone)}
                </p>
              ))}
              {s.reason && !(gapped && s.quietNote) ? (
                <p
                  className={cn(
                    "mt-1",
                    quiet
                      ? "text-text-secondary"
                      : s.level === "unhealthy"
                        ? "text-danger"
                        : "text-warn",
                  )}
                >
                  {s.reason}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
      {hours.length ? (
        <p className="px-3 py-2 text-xs text-text-muted">
          {timesNote(zone)} Each line is scaled to its own busiest hour, the Peak column. Shaded
          hours are gaps.
        </p>
      ) : null}
    </div>
  );
}
