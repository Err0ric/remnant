import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { FilterBar as Bar } from "@/components/FilterBar";
import { api } from "@/lib/api";
import type { LogsRange } from "@/lib/search";

interface FilterBarProps {
  range: LogsRange;
  /** Custom: a start and an end as local date-times (an empty side is open). A page's own
   * window (a drill-through) arrives as Custom. */
  custom?: { from: string; to: string } | null;
  onRange: (range: LogsRange) => void;
  onCustom: (from: string, to: string) => void;
  sources: string[];
  onSources: (sources: string[]) => void;
}

const SOURCES_SQL =
  "SELECT source_id, count(*) AS events FROM events GROUP BY source_id ORDER BY source_id";

/** The sources the viewer may read, for a source filter (Logs and Ask AI share it). */
export const sourceOptions = {
  // Its own key: ["sources"] once also held api.sources (a list), and a Dashboard opened
  // after Search read this result instead and failed on .map (owner, 2026-11-03; D194).
  queryKey: ["search-source-filter"],
  queryFn: () => api.query({ sql: SOURCES_SQL }),
  staleTime: 60_000,
};

export function FilterBar({
  range,
  custom,
  onRange,
  onCustom,
  sources,
  onSources,
}: FilterBarProps) {
  const available = useQuery(sourceOptions);
  const options = (available.data?.rows ?? []).map((r) => String(r[0]));
  const toggle = (id: string) =>
    onSources(sources.includes(id) ? sources.filter((s) => s !== id) : [...sources, id]);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Bar
        label="Filter events"
        time={{
          value: custom ? "custom" : range,
          // Custom opens with both sides open: everything kept, until a date is set.
          onChange: (id) => (id === "custom" ? onCustom("", "") : onRange(id)),
          custom: { from: custom?.from ?? "", to: custom?.to ?? "", onChange: onCustom },
        }}
        isDefault
      />
      {sources.map((s) => (
        <span
          key={s}
          className="flex items-center gap-1 rounded-chip bg-accent-subtle py-0.5 pl-2.5 pr-1.5 text-sm text-accent-text"
        >
          Source: {s}
          <button
            type="button"
            aria-label={`Remove source ${s}`}
            onClick={() => toggle(s)}
            className="rounded-full p-0.5 hover:bg-white/10"
          >
            <X size={12} aria-hidden />
          </button>
        </span>
      ))}
      <label className="flex items-center gap-1 text-sm text-accent-text">
        <span className="sr-only">Add source filter</span>
        <select
          aria-label="Add source filter"
          value=""
          onChange={(e) => e.target.value && toggle(e.target.value)}
          className="cursor-pointer border-0 bg-transparent text-sm text-accent-text focus:outline-none"
        >
          <option value="" className="bg-surface text-text">
            + Add source filter
          </option>
          {options
            .filter((o) => !sources.includes(o))
            .map((o) => (
              <option key={o} value={o} className="bg-surface text-text">
                {o}
              </option>
            ))}
        </select>
      </label>
    </div>
  );
}
