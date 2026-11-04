import type { KeyboardEvent } from "react";
import type { SearchTab } from "@/lib/simpleSearch";

interface SearchTabsProps {
  active: SearchTab;
  onSelect: (tab: SearchTab) => void;
  /** Admins and analysts; auditors have no Ask tab. */
  canAsk: boolean;
}

const LABELS: Record<SearchTab, string> = { simple: "Search", ask: "Ask AI", sql: "SQL" };

/** Search (Simple syntax), Ask AI (plain English), and SQL (ADR-0016 row 1; owner,
 * 2026-11-03: labeled tabs instead of the small AI switch, so Ask is easy to find). */
export function SearchTabs({ active, onSelect, canAsk }: SearchTabsProps) {
  const tabs: SearchTab[] = canAsk ? ["simple", "ask", "sql"] : ["simple", "sql"];
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
      aria-label="How to search"
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
