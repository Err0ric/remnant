import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/cn";

/** One layer of a trend. `color` is a token name from tokens.css ("warn", "local-text"). */
export interface TrendSeries {
  key: string;
  label: string;
  values: number[];
  color: string;
}

interface TrendChartProps {
  title: ReactNode;
  note?: ReactNode;
  /** Stacked bottom first when `stacked`; else drawn in order. */
  series: TrendSeries[];
  stacked?: boolean;
  /** The window before on the same points: a faint dashed line. */
  previous?: { label: string; values: number[] };
  /** Hover text for a point ("Oct 24, 3 PM") and the axis text ("Oct 24"). */
  pointLabel: (i: number) => string;
  axisLabel: (i: number) => string;
  /** Points after this index have no data yet: hatched, no line drawn. */
  lastWithData?: number;
  /** What the chart counts, for screen readers ("failed sign-ins per hour"). */
  summary: string;
  legend?: ReactNode;
  height?: number;
  /** Opens a point's rows (ADR-0039): click, or Enter on the focused point. */
  onOpen?: (i: number) => void;
}

const W = 1000; // viewBox width; the plot stretches to its box, strokes do not scale

/** Round a chart's top up to 1, 2, or 5 times a power of ten, so ticks read easily. */
export function niceTop(n: number): number {
  const p = 10 ** Math.floor(Math.log10(Math.max(1, n)));
  return ([1, 2, 5, 10].find((m) => m * p >= n) ?? 10) * p;
}

/** Monotone tangents (Fritsch and Carlson) per point, in value per step: the curve never
 * overshoots its points, so a count never dips below zero between two hours. */
function tangents(y: number[]): number[] {
  const n = y.length;
  const m = new Array<number>(n).fill(0);
  if (n < 2) return m;
  const d = y.slice(1).map((v, i) => v - (y[i] ?? 0));
  m[0] = d[0] ?? 0;
  m[n - 1] = d[n - 2] ?? 0;
  for (let i = 1; i < n - 1; i++) {
    const a = d[i - 1] ?? 0;
    const b = d[i] ?? 0;
    m[i] = a * b <= 0 ? 0 : (a + b) / 2;
  }
  for (let i = 0; i < n - 1; i++) {
    const di = d[i] ?? 0;
    if (di === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = (m[i] ?? 0) / di;
    const b = (m[i + 1] ?? 0) / di;
    const s = a * a + b * b;
    if (s > 9) {
      const t = 3 / Math.sqrt(s);
      m[i] = t * a * di;
      m[i + 1] = t * b * di;
    }
  }
  return m;
}

/** Cubic segments through the points, forward or backward, without the opening move. */
function segments(
  xs: number[],
  v: number[],
  m: number[],
  y: (n: number) => number,
  backward = false,
): string {
  const out: string[] = [];
  const idx = xs.map((_, i) => i);
  if (backward) idx.reverse();
  for (let k = 0; k < idx.length - 1; k++) {
    const i = idx[k] as number;
    const j = idx[k + 1] as number;
    const dx = ((xs[j] as number) - (xs[i] as number)) / 3;
    const step = j > i ? 1 : -1;
    out.push(
      `C${(xs[i] as number) + dx},${y((v[i] as number) + (step * (m[i] as number)) / 3)} ` +
        `${(xs[j] as number) - dx},${y((v[j] as number) - (step * (m[j] as number)) / 3)} ` +
        `${xs[j]},${y(v[j] as number)}`,
    );
  }
  return out.join(" ");
}

/** A short area chart for the Dashboard (owner 2026-10-30): at most 160 px tall, smooth
 * monotone curves, values on hover or with the arrow keys, an optional stack, and the
 * window before as a faint dashed line. */
export function TrendChart({
  title,
  note,
  series,
  stacked = false,
  previous,
  pointLabel,
  axisLabel,
  lastWithData,
  summary,
  legend,
  height = 140,
  onOpen,
}: TrendChartProps) {
  const n = Math.max(0, ...series.map((s) => s.values.length));
  const last = Math.min(n - 1, lastWithData ?? n - 1);
  const [at, setAt] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const tipId = useId();
  const h = Math.min(160, height);

  // Layers as drawn: cumulative when stacked. A stack's tangents are the sums of its
  // layers' tangents, so bands never cross between points.
  const own = series.map((s) => s.values.slice(0, last + 1));
  const ownM = own.map(tangents);
  const layers = own.map((vals, k) =>
    stacked ? vals.map((_, i) => own.slice(0, k + 1).reduce((a, l) => a + (l[i] ?? 0), 0)) : vals,
  );
  const layerM = ownM.map((ms, k) =>
    stacked ? ms.map((_, i) => ownM.slice(0, k + 1).reduce((a, l) => a + (l[i] ?? 0), 0)) : ms,
  );
  const prev = previous?.values.slice(0, n) ?? [];
  const top = niceTop(Math.max(2, ...layers.flatMap((l) => l), ...(prev.length ? prev : [0])));
  const x = (i: number) => (n <= 1 ? W / 2 : (i / (n - 1)) * W);
  const y = (v: number) => h - (Math.max(0, v) / top) * h;
  const xs = Array.from({ length: last + 1 }, (_, i) => x(i));
  const pct = (i: number) => (n <= 1 ? 50 : (i / (n - 1)) * 100);

  const pick = (clientX: number) => {
    const r = box.current?.getBoundingClientRect();
    if (!r || r.width === 0 || n === 0) return;
    const i = Math.round(((clientX - r.left) / r.width) * (n - 1));
    setAt(Math.max(0, Math.min(n - 1, i)));
  };
  const onKey = (e: KeyboardEvent) => {
    const go = (i: number) => {
      e.preventDefault();
      setAt(Math.max(0, Math.min(n - 1, i)));
    };
    if (e.key === "ArrowLeft") go((at ?? n) - 1);
    else if (e.key === "ArrowRight") go((at ?? -1) + 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(n - 1);
    else if (e.key === "Escape") setAt(null);
    else if (e.key === "Enter" && onOpen && at !== null && at <= last) {
      e.preventDefault();
      onOpen(at);
    }
  };

  const rows =
    at === null
      ? []
      : at > last
        ? [{ key: "none", label: "No data yet", value: null as number | null, color: "" }]
        : [
            ...[...series].reverse().map((s) => ({
              key: s.key,
              label: s.label,
              value: s.values[at] ?? 0,
              color: s.color,
            })),
          ];
  const total = at !== null && at <= last ? series.reduce((a, s) => a + (s.values[at] ?? 0), 0) : 0;
  const tipText =
    at === null
      ? ""
      : `${pointLabel(at)}: ${rows.map((r) => (r.value === null ? r.label : `${r.label} ${r.value.toLocaleString()}`)).join(", ")}${
          stacked && at <= last ? `, total ${total.toLocaleString()}` : ""
        }${previous && prev[at] !== undefined ? `, ${previous.label} ${prev[at].toLocaleString()}` : ""}`;
  const mid = Math.floor((n - 1) / 2);

  return (
    <figure className="min-w-0">
      <figcaption className="mb-1 text-sm font-semibold">
        {title} {note ? <span className="font-normal text-text-muted">{note}</span> : null}
      </figcaption>
      {legend ? <div className="mb-1.5">{legend}</div> : null}
      <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2">
        <div
          aria-hidden="true"
          className="flex flex-col justify-between text-right font-mono text-xs tabular-nums text-text-muted"
          style={{ height: h }}
        >
          <span className="-mt-1.5">{top.toLocaleString()}</span>
          <span>{(top / 2).toLocaleString()}</span>
          <span className="-mb-1.5">0</span>
        </div>
        <div
          ref={box}
          role="img"
          tabIndex={0}
          aria-label={`${summary}. Use the arrow keys for values${onOpen ? ", Enter to open a point in Search" : ""}.`}
          data-drill={onOpen ? "" : undefined}
          onClick={(e) => {
            if (!onOpen) return;
            pick(e.clientX);
            const r = box.current?.getBoundingClientRect();
            if (!r || r.width === 0) return;
            const i = Math.max(
              0,
              Math.min(n - 1, Math.round(((e.clientX - r.left) / r.width) * (n - 1))),
            );
            if (i <= last) onOpen(i);
          }}
          aria-describedby={at !== null ? tipId : undefined}
          onPointerMove={(e) => pick(e.clientX)}
          onPointerLeave={() => setAt(null)}
          onBlur={() => setAt(null)}
          onKeyDown={onKey}
          className={cn(
            "relative border-b border-l border-border outline-none focus-visible:ring-1 focus-visible:ring-focus-ring",
            onOpen && "cursor-pointer",
          )}
          style={{ height: h }}
        >
          <div
            aria-hidden="true"
            className="absolute inset-x-0 top-1/2 border-t border-dashed border-border"
          />
          {last < n - 1 ? (
            <div
              aria-hidden="true"
              className="absolute inset-y-0 right-0"
              style={{
                left: `${pct(last)}%`,
                backgroundImage:
                  "repeating-linear-gradient(135deg, var(--border) 0 1px, transparent 1px 6px)",
              }}
            />
          ) : null}
          <svg
            aria-hidden="true"
            viewBox={`0 0 ${W} ${h}`}
            preserveAspectRatio="none"
            className="absolute inset-0 h-full w-full overflow-visible"
          >
            {prev.length > 1 ? (
              <path
                d={`M${x(0)},${y(prev[0] ?? 0)} ${segments(
                  prev.map((_, i) => x(i)),
                  prev,
                  tangents(prev),
                  y,
                )}`}
                fill="none"
                stroke="var(--text-muted)"
                strokeOpacity={0.55}
                strokeWidth={1.25}
                strokeDasharray="4 3"
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
            {xs.length > 1
              ? layers.map((l, k) => {
                  const s = series[k] as TrendSeries;
                  const m = layerM[k] as number[];
                  const below = stacked && k > 0 ? (layers[k - 1] as number[]) : null;
                  const belowM = stacked && k > 0 ? (layerM[k - 1] as number[]) : null;
                  const upper = `M${xs[0]},${y(l[0] ?? 0)} ${segments(xs, l, m, y)}`;
                  const area = below
                    ? `${upper} L${xs[xs.length - 1]},${y(below[below.length - 1] ?? 0)} ${segments(xs, below, belowM as number[], y, true)} Z`
                    : `${upper} L${xs[xs.length - 1]},${h} L${xs[0]},${h} Z`;
                  return (
                    <g key={s.key}>
                      <path
                        d={area}
                        fill={`var(--${s.color})`}
                        fillOpacity={stacked ? 0.32 : 0.16}
                      />
                      <path
                        d={upper}
                        fill="none"
                        stroke={`var(--${s.color})`}
                        strokeWidth={1.5}
                        vectorEffect="non-scaling-stroke"
                      />
                    </g>
                  );
                })
              : null}
          </svg>
          {at !== null ? (
            <>
              <div
                aria-hidden="true"
                className="absolute inset-y-0 border-l border-border-strong"
                style={{ left: `${pct(at)}%` }}
              />
              {at <= last
                ? layers.map((l, k) => (
                    <span
                      key={series[k]?.key ?? k}
                      aria-hidden="true"
                      className="absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-surface"
                      style={{
                        left: `${pct(at)}%`,
                        top: `${(y(l[at] ?? 0) / h) * 100}%`,
                        background: `var(--${series[k]?.color ?? "text"})`,
                      }}
                    />
                  ))
                : null}
              <div
                id={tipId}
                role="tooltip"
                className={cn(
                  "pointer-events-none absolute top-1 z-10 rounded border border-border-strong bg-surface-head px-2 py-1.5 text-sm shadow",
                  pct(at) > 60 ? "-translate-x-[calc(100%+8px)]" : "translate-x-2",
                )}
                style={{ left: `${pct(at)}%` }}
              >
                <span className="sr-only">{tipText}</span>
                <div aria-hidden="true">
                  <div className="mb-0.5 whitespace-nowrap font-semibold">{pointLabel(at)}</div>
                  {rows.map((r) => (
                    <div key={r.key} className="flex items-center gap-2 whitespace-nowrap">
                      {r.color ? (
                        <span
                          className="inline-block size-2 rounded-sm"
                          style={{ background: `var(--${r.color})` }}
                        />
                      ) : null}
                      <span className="text-text-secondary">{r.label}</span>
                      {r.value !== null ? (
                        <span className="ml-auto pl-3 font-mono tabular-nums">
                          {r.value.toLocaleString()}
                        </span>
                      ) : null}
                    </div>
                  ))}
                  {stacked && at <= last ? (
                    <div className="flex gap-2 whitespace-nowrap border-t border-border pt-0.5">
                      <span className="text-text-secondary">Total</span>
                      <span className="ml-auto font-mono tabular-nums">
                        {total.toLocaleString()}
                      </span>
                    </div>
                  ) : null}
                  {onOpen && at <= last ? (
                    <div className="mt-0.5 whitespace-nowrap text-xs text-accent-text">
                      Open{" "}
                      {stacked ? total.toLocaleString() : (rows[0]?.value ?? 0).toLocaleString()}{" "}
                      events in Search
                    </div>
                  ) : null}
                  {previous && prev[at] !== undefined ? (
                    <div className="flex gap-2 whitespace-nowrap text-text-muted">
                      <span>{previous.label}</span>
                      <span className="ml-auto pl-3 font-mono tabular-nums">
                        {prev[at].toLocaleString()}
                      </span>
                    </div>
                  ) : null}
                </div>
              </div>
            </>
          ) : null}
        </div>
        <span />
        <div className="mt-1 flex justify-between font-mono text-xs tabular-nums text-text-muted">
          <span>{n ? axisLabel(0) : ""}</span>
          {n > 2 ? <span>{axisLabel(mid)}</span> : null}
          <span>{n ? axisLabel(n - 1) : ""}</span>
        </div>
      </div>
    </figure>
  );
}

/** A swatch legend: solid for a series, dashed for the window before. */
export function TrendLegend({
  items,
}: {
  items: { label: ReactNode; color?: string; dashed?: boolean }[];
}) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-text-secondary">
      {items.map((it, i) => (
        <li key={i} className="flex items-center gap-1.5">
          {it.dashed ? (
            <span
              aria-hidden="true"
              className="inline-block w-3.5 border-t border-dashed border-text-muted"
            />
          ) : (
            <span
              aria-hidden="true"
              className="inline-block size-2.5 rounded-sm"
              style={{ background: `var(--${it.color ?? "text"})` }}
            />
          )}
          {it.label}
        </li>
      ))}
    </ul>
  );
}
