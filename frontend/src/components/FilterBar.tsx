import type { ReactNode } from "react";
import { LOOK, Select } from "@/components/forms/Select";
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
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: SegmentedProps<T>) {
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

interface CustomRangeProps {
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
}

/** Custom's two sides, From and To, shown while Custom is chosen. */
export function CustomRange({ from, to, onChange }: CustomRangeProps) {
  return (
    <span className="flex items-center gap-1.5 text-text-secondary">
      <CustomTime label="From" value={from} max={to} onChange={(v) => onChange(v, to)} />
      to
      <CustomTime label="To" value={to} min={from} onChange={(v) => onChange(from, v)} />
    </span>
  );
}

interface FacetSelectProps extends Facet {
  disabled?: boolean;
  /** Drawn inside the button after the value (Ask's Model chip: the Local or Cloud badge). */
  after?: ReactNode;
}

/** A facet button that reads "Name Value" and opens its list (DESIGN.md 6.0). */
export function FacetSelect({ name, value, options, onChange, disabled, after }: FacetSelectProps) {
  return (
    <Select
      look="facet"
      aria-label={name}
      prefix={name}
      value={value}
      disabled={disabled}
      options={options.map((o) => ({ value: o.id, label: o.label }))}
      onChange={onChange}
      suffix={after ? <span className="flex items-center">{after}</span> : null}
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
      {time?.custom && time.value === "custom" ? <CustomRange {...time.custom} /> : null}
      {state ? (
        <Segmented
          label={state.label ?? "State"}
          value={state.value}
          options={state.options}
          onChange={state.onChange}
        />
      ) : null}
      {facets.map((f) => (
        <FacetSelect key={f.name} {...f} />
      ))}
      {text ? (
        <input
          aria-label={text.label}
          placeholder={text.label}
          value={text.value}
          onChange={(e) => text.onChange(e.target.value)}
          // Drawn as the facet buttons beside it, so it never reads as disabled.
          className={cn(LOOK.facet, "w-56 min-w-0 text-text placeholder:text-text-secondary")}
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
