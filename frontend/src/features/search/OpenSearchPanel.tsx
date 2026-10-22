import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, type SavedSearch } from "@/lib/api";

interface OpenSearchPanelProps {
  onOpen: (search: SavedSearch) => void;
  onClose: () => void;
}

/** Open a saved search on the Search page (install finding 13): newest first, filterable. */
export function OpenSearchPanel({ onOpen, onClose }: OpenSearchPanelProps) {
  const searches = useQuery({ queryKey: ["searches"], queryFn: api.searches });
  const [filter, setFilter] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);

  const needle = filter.trim().toLowerCase();
  const list = [...(searches.data ?? [])]
    .filter(
      (s) =>
        !needle ||
        s.name.toLowerCase().includes(needle) ||
        s.id.includes(needle) ||
        s.tags.some((t) => t.toLowerCase().includes(needle)),
    )
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .slice(0, 50);

  return (
    <section
      aria-label="Open a saved search"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
      className="rounded-card border border-border bg-surface"
    >
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <label htmlFor="open-search-filter" className="text-sm font-semibold">
          Open a saved search
        </label>
        <input
          id="open-search-filter"
          ref={input}
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Name, id, or tag"
          autoComplete="off"
          className="h-8 min-w-0 flex-1 rounded border border-border-strong bg-inset px-2 text-sm"
        />
        <button
          type="button"
          onClick={onClose}
          className="h-8 rounded px-3 text-sm hover:bg-surface-head"
        >
          Close
        </button>
      </div>
      {searches.isPending ? (
        <p className="px-3 py-2 text-sm text-text-muted">Loading saved searches…</p>
      ) : searches.isError ? (
        <p role="alert" className="px-3 py-2 text-sm text-sev-critical-text">
          Saved searches could not be loaded.
        </p>
      ) : list.length === 0 ? (
        <p className="px-3 py-2 text-sm text-text-muted">
          {needle ? "No saved search matches." : "No saved searches yet. Write a query, then Save."}
        </p>
      ) : (
        <ul className="max-h-80 overflow-y-auto py-1">
          {list.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onOpen(s)}
                className="flex w-full flex-wrap items-baseline gap-x-3 px-3 py-1.5 text-left hover:bg-surface-head focus:bg-surface-head focus:outline-none"
              >
                <span className="text-sm text-text">{s.name}</span>
                <span className="font-mono text-xs text-text-muted">{s.id}</span>
                <span className="ml-auto text-xs text-text-muted">
                  {s.visibility === "shared" ? "Shared" : "Private"}
                  {s.tags.length ? `, ${s.tags.join(", ")}` : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
