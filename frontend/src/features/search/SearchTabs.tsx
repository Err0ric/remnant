import type { KeyboardEvent } from "react";

export type SearchArea = "search" | "sql";

interface SearchTabsProps {
  active: SearchArea;
  onSelect: (area: SearchArea) => void;
}

const LABELS: Record<SearchArea, string> = { search: "Search", sql: "SQL" };
const AREAS: SearchArea[] = ["search", "sql"];

/** Search (Simple syntax, or plain English with the AI toggle) and SQL (ADR-0016 row 1). */
export function SearchTabs({ active, onSelect }: SearchTabsProps) {
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const next = active === "search" ? "sql" : "search";
    onSelect(next);
    document.getElementById(`search-tab-${next}`)?.focus();
  };
  return (
    <div
      role="tablist"
      aria-label="How to search"
      onKeyDown={onKeyDown}
      className="flex gap-1 border-b border-border"
    >
      {AREAS.map((t) => (
        <button
          key={t}
          id={`search-tab-${t}`}
          type="button"
          role="tab"
          aria-selected={active === t}
          aria-controls={`search-panel-${t}`}
          tabIndex={active === t ? 0 : -1}
          onClick={() => onSelect(t)}
          className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${
            active === t
              ? "border-accent font-semibold text-text"
              : "border-transparent text-text-secondary hover:text-text"
          }`}
        >
          {LABELS[t]}
        </button>
      ))}
    </div>
  );
}
