import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { sourceOptions } from "@/features/search/FilterBar";

interface SourcesChipProps {
  sources: string[];
  onSources: (sources: string[]) => void;
}

/** Ask AI's Sources facet (D256): "Sources All 8", or the chosen ones; opens the list of
 * sources the viewer may read, each a checkbox. None chosen means all of them. */
export function SourcesChip({ sources, onSources }: SourcesChipProps) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const listId = useId();
  const available = useQuery(sourceOptions);
  const options = (available.data?.rows ?? []).map((r) => String(r[0]));
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  const toggle = (id: string) =>
    onSources(sources.includes(id) ? sources.filter((s) => s !== id) : [...sources, id]);
  const value = sources.length
    ? sources.join(", ")
    : available.data
      ? `All ${options.length}`
      : "All";
  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={() => setOpen(!open)}
        className="flex h-7 max-w-64 items-center gap-1.5 rounded border border-border-strong px-2.5 text-text-secondary"
      >
        Sources
        <span className="truncate font-semibold text-text">{value}</span>
        <ChevronDown size={14} strokeWidth={1.5} aria-hidden className="shrink-0" />
      </button>
      {open ? (
        <div
          id={listId}
          role="group"
          aria-label="Sources"
          className="absolute left-0 top-full z-30 mt-1 flex max-h-64 min-w-48 flex-col overflow-y-auto rounded-card border border-border bg-surface py-1 shadow-lg"
        >
          <label className="flex items-center gap-2 px-3 py-1.5 hover:bg-surface-head">
            <input type="checkbox" checked={sources.length === 0} onChange={() => onSources([])} />
            All sources
          </label>
          {options.map((o) => (
            <label
              key={o}
              className="flex items-center gap-2 px-3 py-1.5 font-mono hover:bg-surface-head"
            >
              <input type="checkbox" checked={sources.includes(o)} onChange={() => toggle(o)} />
              {o}
            </label>
          ))}
        </div>
      ) : null}
    </div>
  );
}
