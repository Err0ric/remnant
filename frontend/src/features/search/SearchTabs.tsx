import type { KeyboardEvent } from "react";
import type { SearchTab } from "@/lib/simpleSearch";

interface SearchTabsProps {
  active: SearchTab;
  onSelect: (tab: SearchTab) => void;
}

const LABELS: Record<SearchTab, string> = { simple: "Filters", sql: "SQL" };
const TABS: SearchTab[] = ["simple", "sql"];

/** The two modes of Logs (D206): Filters (the Simple syntax) and SQL. Ask AI is its own
 * page, not a mode here. */
export function SearchTabs({ active, onSelect }: SearchTabsProps) {
  const tabs = TABS;
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const at = Math.max(tabs.indexOf(active), 0);
    const step = e.key === "ArrowRight" ? 1 : tabs.length - 1;
    const next = tabs[(at + step) % tabs.length] as SearchTab;
    onSelect(next);
    document.getElementById(`search-tab-${next}`)?.focus();
  };
  return (
    <div
      role="tablist"
      aria-label="Logs mode"
      onKeyDown={onKeyDown}
      className="flex gap-1 border-b border-border"
    >
      {tabs.map((t) => (
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
