import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { utcText } from "@/lib/timeWindow";

/** The five time presets every page with a time control offers (DESIGN.md 6.0). */
export const TIME_PRESETS = [
  { id: "1h", label: "1 hour" },
  { id: "24h", label: "24 hours" },
  { id: "7d", label: "7 days" },
  { id: "30d", label: "30 days" },
  { id: "custom", label: "Custom" },
] as const;
export type TimePreset = (typeof TIME_PRESETS)[number]["id"];

export interface Segment<T extends string = string> {
  id: T;
  label: string;
  /** Shown beside the label ("Open 7"); left out when not known. */
  count?: number | null;
}

export interface Facet {
  /** The facet's name, read before its value: "Severity High". */
  name: string;
  value: string;
  options: { id: string; label: string }[];
  onChange: (id: string) => void;
}

interface SegmentedProps<T extends string> {
  label: string;
  value: T;
  options: readonly Segment<T>[];
  onChange: (id: T) => void;
}

/** A segmented control: one of a few choices, the pressed one on the pressed fill. */
function Segmented<T extends string>({ label, value, options, onChange }: SegmentedProps<T>) {
  return (
    <div role="group" aria-label={label} className="flex rounded border border-border-strong">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          aria-pressed={value === o.id}
          // Pressing the choice already made changes nothing (it must not clear Custom's dates).
          onClick={() => (value === o.id ? undefined : onChange(o.id))}
          className={cn(
            "h-7 whitespace-nowrap px-2.5 first:rounded-l last:rounded-r",
            value === o.id
              ? "bg-accent-subtle font-semibold text-accent-text"
              : "text-text-secondary hover:text-text",
          )}
        >
          {o.label}
          {o.count !== undefined && o.count !== null ? (
            <>
              {" "}
              <span className="ml-0.5 font-mono text-xs tabular-nums">{o.count}</span>
            </>
          ) : null}
        </button>
      ))}
    </div>
  );
}

interface CustomTimeProps {
  label: string;
  value: string;
  min?: string;
  max?: string;
  onChange: (value: string) => void;
}

/** One side of Custom: a date and time in the viewer's time zone, with UTC on hover
 * (DESIGN.md 3). Empty leaves that side open. */
function CustomTime({ label, value, min, max, onChange }: CustomTimeProps) {
  return (
    <input
      type="datetime-local"
      aria-label={label}
      title={utcText(value) || `${label}: your local time`}
      value={value}
      min={min || undefined}
      max={max || undefined}
      onChange={(e) => onChange(e.target.value)}
      className="h-7 rounded border border-border-control bg-inset px-1.5 font-mono text-text"
    />
  );
}

interface FilterBarProps<S extends string> {
  /** What the bar filters, for its accessible name ("Filter alerts"). */
  label: string;
  /** One time control per page; left out on a page with no time filter. */
  time?: {
    value: TimePreset;
    onChange: (id: TimePreset) => void;
    /** The start and end of Custom, as local date-times; shown while Custom is pressed. */
    custom?: { from: string; to: string; onChange: (from: string, to: string) => void };
  };
  state?: { label?: string; value: S; options: readonly Segment<S>[]; onChange: (id: S) => void };
  facets?: Facet[];
  text?: { label: string; value: string; onChange: (value: string) => void };
  /** Right side: rows the caller can read ("7 alerts", "3 of 7 alerts"). */
  count?: ReactNode;
  /** Right side, after the count: the Columns control of a table page. */
  columns?: ReactNode;
  /** Shown only while the filters differ from the page's default. */
  onReset?: () => void;
  isDefault: boolean;
}

/** The filter bar (DESIGN.md 6.0, zone 3): one row in a fixed order, Time, State, facets,
 * text box, with the count and Columns on the right. A facet reads "Name Value" in one
 * control. Reset appears only when the filters differ from the page's default. The page
 * keeps the filter state in the URL fragment. */
export function FilterBar<S extends string>({
  label,
  time,
  state,
  facets = [],
  text,
  count,
  columns,
  onReset,
  isDefault,
}: FilterBarProps<S>) {
  return (
    <div
      role="group"
      aria-label={label}
      data-filter-bar=""
      className="flex min-h-10 flex-wrap items-center gap-2 text-sm"
    >
      {time ? (
        <Segmented
          label="Time"
          value={time.value}
          options={TIME_PRESETS}
          onChange={time.onChange}
        />
      ) : null}
      {time?.custom && time.value === "custom" ? (
        <span className="flex items-center gap-1.5 text-text-secondary">
          <CustomTime
            label="From"
            value={time.custom.from}
            max={time.custom.to}
            onChange={(v) => time.custom?.onChange(v, time.custom.to)}
          />
          to
          <CustomTime
            label="To"
            value={time.custom.to}
            min={time.custom.from}
            onChange={(v) => time.custom?.onChange(time.custom.from, v)}
          />
        </span>
      ) : null}
      {state ? (
        <Segmented
          label={state.label ?? "State"}
          value={state.value}
          options={state.options}
          onChange={state.onChange}
        />
      ) : null}
      {facets.map((f) => (
        <label
          key={f.name}
          className="flex h-7 items-center gap-1.5 rounded border border-border-strong pl-2.5 text-text-secondary focus-within:outline focus-within:outline-2 focus-within:outline-focus-ring"
        >
          {f.name}
          <select
            aria-label={f.name}
            value={f.value}
            onChange={(e) => f.onChange(e.target.value)}
            className="h-full rounded-r bg-transparent pr-1 font-semibold text-text focus:outline-none"
          >
            {f.options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      ))}
      {text ? (
        <input
          aria-label={text.label}
          placeholder={text.label}
          value={text.value}
          onChange={(e) => text.onChange(e.target.value)}
          className="h-7 w-56 min-w-0 rounded border border-border-control bg-inset px-2"
        />
      ) : null}
      {!isDefault && onReset ? (
        <button
          type="button"
          onClick={onReset}
          className="h-7 px-1.5 text-accent-text hover:underline"
        >
          Reset
        </button>
      ) : null}
      {count !== undefined && count !== null ? (
        <span data-filter-count="" className="ml-auto tabular-nums text-text-secondary">
          {count}
        </span>
      ) : null}
      {columns ? (
        <span className={count === undefined || count === null ? "ml-auto" : ""}>{columns}</span>
      ) : null}
    </div>
  );
}
