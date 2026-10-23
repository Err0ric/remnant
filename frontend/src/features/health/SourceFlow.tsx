import { useEffect } from "react";
import type { Overview, SourceGap } from "@/lib/api";
import { stamp } from "@/features/overview/time";
import { gapText, lag, localHour, zoneName } from "./flow";

export type FlowLevel = "unhealthy" | "attention" | "paused" | "healthy";

export interface FlowSource {
  source_id: string;
  level: FlowLevel;
  word?: string;
  reason?: string | null;
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

const DOT: Record<FlowLevel, string> = {
  unhealthy: "bg-danger",
  attention: "bg-warn",
  paused: "bg-text-muted",
  healthy: "bg-ok",
};
const WORD: Record<FlowLevel, string> = {
  unhealthy: "Unhealthy",
  attention: "Needs attention",
  paused: "Paused",
  healthy: "Flowing",
};
const COLS =
  "grid grid-cols-1 gap-x-4 gap-y-1 md:grid-cols-[minmax(9rem,13rem)_minmax(8rem,1fr)_5.5rem_5.5rem_6rem]";

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
}

/** Events per hour as an area, the source's own peak printed, gap hours shaded (F55). The
 * reading for each hour is in a tooltip; the totals beside it are printed. */
function Spark({ counts, hours, gaps, name, timeZone }: SparkProps) {
  const n = Math.max(1, counts.length);
  const peak = Math.max(0, ...counts);
  const top = Math.max(1, peak);
  const x = (i: number) => (i / (n - 1 || 1)) * 100;
  const y = (v: number) => 26 - (v / top) * 22;
  const line = counts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(v).toFixed(2)}`);
  const area = `${line.join(" ")} L100,28 L0,28 Z`;
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
    <div className="relative h-8 min-w-0">
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
        <path d={area} className="fill-accent opacity-20" />
        <path
          d={line.join(" ")}
          className="fill-none stroke-accent-text"
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
      <span className="pointer-events-none absolute right-0 top-0 font-mono text-xs tabular-nums text-text-muted">
        peak {compact(peak)}/h
      </span>
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
        className={`${COLS} border-b border-border bg-surface-head px-3 py-2 text-text-secondary max-md:hidden`}
      >
        <span className="font-semibold">Source</span>
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
        <span className="text-right font-semibold">24 hours</span>
        <span className="text-right font-semibold">Per minute</span>
        <span className="text-right font-semibold">Last received</span>
      </div>
      <ul aria-label="Sources">
        {sources.map((s) => {
          const v = volume.get(s.source_id);
          const h = health.get(s.source_id);
          const counts = v?.counts ?? hours.map(() => 0);
          const gaps = v?.gaps ?? [];
          const last = h?.last_event_at ?? s.last;
          const ago = lag(last, now);
          return (
            <li
              key={s.source_id}
              id={`flow-${s.source_id}`}
              aria-current={focused === s.source_id ? "true" : undefined}
              className={`border-b border-border px-3 py-2 last:border-0 ${focused === s.source_id ? "bg-accent-subtle" : ""}`}
            >
              <div className={`${COLS} items-center`}>
                <div className="min-w-0">
                  {s.onOpen ? (
                    <button
                      type="button"
                      onClick={s.onOpen}
                      className="text-left font-mono text-accent-text [overflow-wrap:anywhere] hover:underline"
                    >
                      {s.source_id}
                    </button>
                  ) : (
                    <span className="font-mono [overflow-wrap:anywhere]">{s.source_id}</span>
                  )}
                  <div className="flex items-center gap-1.5 text-xs text-text-secondary">
                    <span
                      aria-hidden
                      className={`inline-block size-2 rounded-full ${DOT[s.level]}`}
                    />
                    {s.word ?? WORD[s.level]}
                  </div>
                </div>
                <Spark
                  counts={counts}
                  hours={hours}
                  gaps={gaps}
                  name={s.source_id}
                  timeZone={timeZone}
                />
                <span className="font-mono tabular-nums md:text-right">
                  {(v?.total ?? 0).toLocaleString()}
                  <span className="text-text-muted md:hidden"> events in 24 h</span>
                </span>
                <span className="font-mono tabular-nums md:text-right">
                  {(h?.rate_per_min ?? 0).toLocaleString()}
                  <span className="text-text-muted md:hidden"> per minute</span>
                </span>
                <span
                  className="font-mono tabular-nums md:text-right"
                  title={last ? `${stamp(last)} UTC` : undefined}
                >
                  {ago ? `${ago} ago` : "never"}
                </span>
              </div>
              {gaps.map((g) => (
                <p key={g.start} className="mt-1 text-danger" title={`From ${stamp(g.start)} UTC`}>
                  {gapText(g, now, timeZone)}
                </p>
              ))}
              {s.reason ? (
                <p className={`mt-1 ${s.level === "unhealthy" ? "text-danger" : "text-warn"}`}>
                  {s.reason}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
      {hours.length ? (
        <p className="px-3 py-2 text-xs text-text-muted">
          Times in {zone}; hover for UTC. Each line is scaled to its own busiest hour, printed at
          the right. Shaded hours are gaps.
        </p>
      ) : null}
    </div>
  );
}
