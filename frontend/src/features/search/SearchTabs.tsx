import type { KeyboardEvent } from "react";
import type { SearchTab } from "@/lib/simpleSearch";

interface SearchTabsProps {
  tab: SearchTab;
  onTab: (tab: SearchTab) => void;
  /** Auditors have no Ask (SPEC 3.6). */
  canAsk: boolean;
}

const LABELS: Record<SearchTab, string> = {
  simple: "Simple",
  ask: "Ask in plain English",
  sql: "SQL",
};

/** The three ways to write a search; one results table under all of them. */
export function SearchTabs({ tab, onTab, canAsk }: SearchTabsProps) {
  const tabs: SearchTab[] = canAsk ? ["simple", "ask", "sql"] : ["simple", "sql"];
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const i = tabs.indexOf(tab);
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    if (next) {
      onTab(next);
      document.getElementById(`search-tab-${next}`)?.focus();
    }
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
          aria-selected={tab === t}
          aria-controls={`search-panel-${t}`}
          tabIndex={tab === t ? 0 : -1}
          onClick={() => onTab(t)}
          className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${
            tab === t
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
