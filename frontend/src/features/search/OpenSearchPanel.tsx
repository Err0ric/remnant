import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, type SavedSearch } from "@/lib/api";
import { clearRecent, goToSearch, recentSearches } from "@/lib/searchUrl";

interface OpenSearchPanelProps {
  onOpen: (search: SavedSearch) => void;
  onClose: () => void;
}

/** Open a saved search on the Search page (install finding 13): newest first, filterable.
 * Above the list, the last 10 runs in this browser (D90), to jump back without saving. */
export function OpenSearchPanel({ onOpen, onClose }: OpenSearchPanelProps) {
  const searches = useQuery({ queryKey: ["searches"], queryFn: api.searches });
  const [filter, setFilter] = useState("");
  const [recent, setRecent] = useState(recentSearches);
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
  const names = new Map((searches.data ?? []).map((s) => [s.id, s.name]));
  const recentShown = recent
    .map((r) => {
      const id = new URLSearchParams(r.url.split("#")[1] ?? "").get("saved");
      const range = new URLSearchParams(r.url.split("#")[1] ?? "").get("range") ?? "";
      return {
        ...r,
        label: id && names.has(id) ? `Saved search: ${names.get(id)}` : r.label,
        range,
      };
    })
    .filter((r) => !needle || r.label.toLowerCase().includes(needle));

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
      {recentShown.length ? (
        <div className="border-b border-border py-1">
          <div className="flex items-center px-3 py-1">
            <h3
              id="recent-searches"
              className="text-xs font-semibold uppercase tracking-wide text-text-muted"
            >
              Recent searches
            </h3>
            <button
              type="button"
              onClick={() => {
                clearRecent();
                setRecent([]);
              }}
              className="ml-auto rounded px-2 text-xs text-text-muted hover:bg-surface-head hover:text-text"
            >
              Clear recent
            </button>
          </div>
          <ul aria-labelledby="recent-searches">
            {recentShown.map((r) => (
              <li key={r.url}>
                <button
                  type="button"
                  onClick={() => goToSearch(r.url)}
                  className="flex w-full items-baseline gap-x-3 px-3 py-1 text-left hover:bg-surface-head focus:bg-surface-head focus:outline-none"
                >
                  <span className="min-w-0 flex-1 truncate font-mono text-xs text-text">
                    {r.label}
                  </span>
                  <span className="shrink-0 text-xs text-text-muted">{r.range}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
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
