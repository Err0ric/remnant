import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api } from "@/lib/api";
import { TIME_RANGES, type TimeRangeId } from "@/lib/search";

interface FilterBarProps {
  range: TimeRangeId;
  /** A page's own window (a drill-through), shown as the selected range until a preset
   * is chosen. */
  custom?: { from: string; to: string } | null;
  onRange: (range: TimeRangeId) => void;
  sources: string[];
  onSources: (sources: string[]) => void;
}

const SOURCES_SQL =
  "SELECT source_id, count(*) AS events FROM events GROUP BY source_id ORDER BY source_id";

const fmt = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

export function FilterBar({ range, custom, onRange, sources, onSources }: FilterBarProps) {
  const available = useQuery({
    queryKey: ["sources"],
    queryFn: () => api.query({ sql: SOURCES_SQL }),
    staleTime: 60_000,
  });
  const options = (available.data?.rows ?? []).map((r) => String(r[0]));
  const toggle = (id: string) =>
    onSources(sources.includes(id) ? sources.filter((s) => s !== id) : [...sources, id]);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="flex items-center gap-2 rounded-chip bg-accent-subtle py-0.5 pl-2.5 pr-1 text-sm text-accent-text">
        Time range:
        <select
          aria-label="Time range"
          value={custom ? "custom" : range}
          onChange={(e) => onRange(e.target.value as TimeRangeId)}
          className="cursor-pointer rounded-chip border-0 bg-transparent pr-1 text-sm font-semibold text-accent-text focus:outline-none"
        >
          {custom ? (
            <option value="custom" className="bg-surface text-text">
              {fmt(custom.from)} to {fmt(custom.to)}
            </option>
          ) : null}
          {TIME_RANGES.map((r) => (
            <option key={r.id} value={r.id} className="bg-surface text-text">
              {r.label}
            </option>
          ))}
        </select>
      </label>
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
