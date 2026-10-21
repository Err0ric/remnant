import { hourLabel } from "./time";

export type HourMark = "" | "busy" | "quiet";

interface HourCellsProps {
  source: string;
  counts: number[];
  /** Start of each hour, ISO, oldest first (same length as `counts`). */
  hours: string[];
  /** Typical count for each hour (median of the same hour on earlier days), or null. */
  typical: (number | null)[];
  marks: HourMark[];
  /** The hour under the pointer in any row, so every row lights the same column. */
  active: number | null;
  onActive: (index: number | null) => void;
  /** This row holds the pointer: show the reading here. */
  showTip: boolean;
  onOpen: (index: number) => void;
}

const MARK_TEXT: Record<HourMark, string> = {
  "": "",
  busy: "busier than usual",
  quiet: "much quieter than usual",
};

function reading(n: number, usual: number | null, mark: HourMark): string {
  const events = `${n.toLocaleString()} ${n === 1 ? "event" : "events"}`;
  const typical = usual === null ? "" : `, usually ${Math.round(usual).toLocaleString()}`;
  return `${events}${typical}${mark ? `, ${MARK_TEXT[mark]}` : ""}`;
}

/** One row of the Overview heatmap: a cell per hour, shaded by count against this source's
 * own busiest hour. Busy hours are outlined and quiet ones striped (D65), so the marks never
 * depend on color alone. A cell opens that source and hour in Search. */
export function HourCells({
  source,
  counts,
  hours,
  typical,
  marks,
  active,
  onActive,
  showTip,
  onOpen,
}: HourCellsProps) {
  const peak = Math.max(1, ...counts);
  return (
    <div
      className="relative grid min-w-[240px] gap-[2px]"
      style={{ gridTemplateColumns: `repeat(${Math.max(1, counts.length)}, minmax(0, 1fr))` }}
      onMouseLeave={() => onActive(null)}
    >
      {counts.map((n, i) => {
        const mark = marks[i] ?? "";
        const usual = typical[i] ?? null;
        return (
          <button
            key={hours[i] ?? i}
            type="button"
            aria-label={`${source}, ${hourLabel(hours[i] ?? "")}: ${reading(n, usual, mark)}. Open in Search`}
            onMouseEnter={() => onActive(i)}
            onFocus={() => onActive(i)}
            onBlur={() => onActive(null)}
            onClick={() => onOpen(i)}
            className={`relative h-6 overflow-hidden rounded-sm bg-inset ${mark === "quiet" ? "hatch" : ""}`}
          >
            {n > 0 ? (
              <span
                aria-hidden
                className="absolute inset-0 bg-accent"
                style={{ opacity: 0.15 + 0.85 * (n / peak) }}
              />
            ) : null}
            {mark === "busy" || active === i ? (
              <span
                aria-hidden
                className={`absolute inset-0 rounded-sm ring-inset ${
                  mark === "busy" ? "ring-2 ring-warn" : "ring-1 ring-text-muted"
                }`}
              />
            ) : null}
          </button>
        );
      })}
      {showTip && active !== null && hours[active] ? (
        <div
          role="tooltip"
          className="pointer-events-none absolute bottom-full z-10 mb-1 whitespace-nowrap rounded border border-border-strong bg-surface-head px-2 py-1 text-xs shadow"
          style={{
            left: `${((active + 0.5) / counts.length) * 100}%`,
            transform: `translateX(${active > counts.length / 2 ? "-100%" : "0"})`,
          }}
        >
          <span className="text-text-secondary">{hourLabel(hours[active])}</span>{" "}
          <span className="font-mono tabular-nums text-text">
            {reading(counts[active] ?? 0, typical[active] ?? null, marks[active] ?? "")}
          </span>
        </div>
      ) : null}
    </div>
  );
}
