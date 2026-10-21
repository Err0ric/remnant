import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useMemo, useState, type KeyboardEvent } from "react";
import { api } from "@/lib/api";
import { setAskProvider, useAskProvider } from "@/lib/askProvider";
import { visibleNav, visibleSections } from "@/lib/nav";
import { arrange, readRecent, rememberRecent, type PaletteItem } from "@/lib/palette";
import { navigate, type PageId } from "@/lib/route";
import { openSavedSearch } from "@/lib/savedSeed";
import { RUN_SEARCH_EVENT, seedSearch } from "@/lib/searchSeed";
import type { Theme } from "@/lib/theme";
import { cn } from "@/lib/cn";

interface CommandPaletteProps {
  page: PageId;
  isAdmin: boolean;
  canAudit: boolean;
  canAsk: boolean;
  theme: Theme;
  onToggleTheme: () => void;
  onClose: () => void;
}

/**
 * Ctrl+K / Cmd+K (DESIGN.md 7): jump to a page, a saved search, or a source, run the
 * current search, or switch theme and AI provider. Lists come from the same APIs as the
 * pages, so everything shown is already limited to what this user may see.
 */
export function CommandPalette({
  page,
  isAdmin,
  canAudit,
  canAsk,
  theme,
  onToggleTheme,
  onClose,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [recent] = useState(readRecent);
  const askProvider = useAskProvider();
  const searches = useQuery({ queryKey: ["searches"], queryFn: api.searches, staleTime: 30_000 });
  const sources = useQuery({ queryKey: ["source-list"], queryFn: api.sources, staleTime: 30_000 });
  const providers = useQuery({
    queryKey: ["ask-providers"],
    queryFn: api.askProviders,
    enabled: canAsk,
    staleTime: 30_000,
  });

  const items = useMemo<PaletteItem[]>(() => {
    const out: PaletteItem[] = visibleNav(isAdmin, canAudit).flatMap((n): PaletteItem[] => [
      {
        key: `nav:${n.id}`,
        section: "Navigate",
        label: n.label,
        aliases: n.aliases,
        run: () => navigate(n.page as PageId),
      },
      ...visibleSections(n, isAdmin).map((x): PaletteItem => ({
        key: `nav:${n.id}:${x.id}`,
        section: "Navigate",
        label: `${n.label} › ${x.label}`,
        run: () => navigate(n.page as PageId, x.id),
      })),
    ]);
    if (canAsk) {
      out.push({
        key: "nav:ask",
        section: "Navigate",
        label: "Ask in plain English",
        hint: "Search",
        aliases: ["seance", "question", "ai"],
        run: () => navigate("ask"),
      });
    }
    out.push({
      key: "nav:me",
      section: "Navigate",
      label: "Your account and API tokens",
      aliases: ["password", "token", "cli"],
      run: () => navigate("me"),
    });
    if (page === "search" || page === "ask") {
      out.push({
        key: "act:run",
        section: "Actions",
        label: "Run the current search",
        aliases: ["query", "execute"],
        run: () => window.dispatchEvent(new Event(RUN_SEARCH_EVENT)),
      });
    }
    out.push({
      key: "act:theme",
      section: "Actions",
      label: `Switch to ${theme === "dark" ? "light" : "dark"} theme`,
      aliases: ["theme", "mode", "dark", "light"],
      run: onToggleTheme,
    });
    const usable = providers.data ?? [];
    const current = usable.find((p) => p.provider_id === askProvider) ?? usable[0];
    for (const p of usable) {
      out.push({
        key: `provider:${p.provider_id}`,
        section: "Actions",
        label: `Use ${p.name} for Ask`,
        hint: `${p.model} · ${p.locality === "cloud" ? "Cloud" : "Local"}${
          p.provider_id === current?.provider_id ? " · current" : ""
        }`,
        aliases: ["provider", "model", "switch"],
        run: () => setAskProvider(p.provider_id),
      });
    }
    for (const s of searches.data ?? []) {
      out.push({
        key: `saved:${s.id}`,
        section: "Saved searches",
        label: s.name,
        hint: s.tags.join(" "),
        aliases: [s.id],
        run: () => {
          openSavedSearch(s.id);
          navigate("saved");
        },
      });
    }
    for (const s of sources.data ?? []) {
      out.push({
        key: `source:${s.source_id}`,
        section: "Sources",
        label: s.source_id,
        hint: "Search this source",
        run: () => {
          seedSearch({ sources: [s.source_id] });
          navigate("search");
        },
      });
    }
    return out;
  }, [
    isAdmin,
    canAudit,
    canAsk,
    page,
    theme,
    onToggleTheme,
    providers.data,
    askProvider,
    searches.data,
    sources.data,
  ]);

  const groups = arrange(items, query, recent);
  const flat = groups.flatMap((g) => g.items);
  const index = Math.min(active, Math.max(flat.length - 1, 0));

  const choose = (item: PaletteItem | undefined) => {
    if (!item) return;
    rememberRecent(item.key);
    onClose();
    item.run();
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((index + 1) % Math.max(flat.length, 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((index - 1 + flat.length) % Math.max(flat.length, 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(flat[index]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  const optionId = (key: string) => `palette-${key.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
  let n = -1;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-[12vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="w-full max-w-[560px] overflow-hidden rounded-card border border-border-strong bg-surface text-text shadow-2xl"
      >
        <div className="flex items-center gap-2 border-b border-border px-3">
          <Search size={16} aria-hidden className="text-text-muted" />
          <input
            autoFocus
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={flat[index] ? optionId(flat[index].key) : undefined}
            aria-label="Search pages, saved searches, sources, and actions"
            placeholder="Go to a page, saved search, or source"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={onKey}
            className="h-11 min-w-0 flex-1 bg-transparent text-base text-text outline-none placeholder:text-text-muted"
          />
          <kbd className="rounded-badge border border-border px-1.5 text-xs text-text-muted">
            Esc
          </kbd>
        </div>
        <div id="palette-list" role="listbox" className="max-h-[60vh] overflow-y-auto py-1">
          {groups.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-text-muted">Nothing matches</p>
          ) : (
            groups.map((g) => (
              <div key={g.section} role="group" aria-label={g.section}>
                <div className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-text-muted">
                  {g.section}
                </div>
                {g.items.map((item) => {
                  n += 1;
                  const mine = n;
                  const selected = mine === index;
                  return (
                    <div
                      key={`${g.section}-${item.key}`}
                      id={selected ? optionId(item.key) : undefined}
                      role="option"
                      aria-selected={selected}
                      onMouseEnter={() => setActive(mine)}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => choose(item)}
                      className={cn(
                        "mx-1 flex cursor-pointer items-center gap-3 rounded px-2.5 py-1.5 text-sm",
                        selected ? "bg-accent-subtle text-text" : "text-text-secondary",
                      )}
                    >
                      <span
                        className={cn(
                          "min-w-0 truncate",
                          item.section === "Sources" ? "font-mono" : "",
                        )}
                      >
                        {item.label}
                      </span>
                      {item.hint ? (
                        <span className="ml-auto shrink-0 truncate text-xs text-text-muted">
                          {item.hint}
                        </span>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
