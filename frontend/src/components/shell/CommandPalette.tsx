import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { api, type LookupHit } from "@/lib/api";
import { CoverageLines } from "@/features/investigate/EmptyAddress";
import { guestLabel, showGuestEvents } from "@/features/investigate/InventoryLine";
import { openEntity } from "@/lib/entity";
import { setAskProvider, useAskProvider } from "@/lib/askProvider";
import { openAsk } from "@/lib/askSlideOver";
import { LOGS_VIEWS, visibleNav, visibleSections } from "@/lib/nav";
import {
  arrange,
  looksLikeQuestion,
  readRecent,
  rememberRecent,
  type PaletteItem,
} from "@/lib/palette";
import { navigate, type PageId } from "@/lib/route";
import { openSavedSearch } from "@/lib/savedSeed";
import { RUN_SEARCH_EVENT, seedSearch } from "@/lib/searchSeed";
import type { Theme } from "@/lib/theme";
import { cn } from "@/lib/cn";
import { useViewer } from "@/lib/viewer";

interface CommandPaletteProps {
  page: PageId;
  isAdmin: boolean;
  canAudit: boolean;
  /** Defaults to the viewer's (Ask follows the Auditor SQL setting, D220). */
  canAsk?: boolean;
  theme: Theme;
  onToggleTheme: () => void;
  onClose: () => void;
}

const SECTIONS = {
  ip: "Addresses",
  user: "People",
  host: "Hosts",
  service: "AI services",
} as const;

function count(n: number | null): string {
  return n === null ? "" : `${n.toLocaleString()} ${n === 1 ? "event" : "events"}`;
}

/** One entity from the lookup; opening it goes to its page. */
function hitItem(h: LookupHit): PaletteItem {
  const where = h.geo
    ? [
        h.geo.country_name ?? h.geo.country,
        h.geo.asn ? `AS${h.geo.asn} ${h.geo.org ?? ""}`.trim() : null,
      ]
        .filter(Boolean)
        .join(", ")
    : "";
  return {
    key: `entity:${h.kind}:${h.value}`,
    section: SECTIONS[h.kind],
    label: h.label,
    hint:
      h.kind === "service"
        ? "AI service"
        : [where, h.aliases?.length ? `also ${h.aliases.join(", ")}` : "", count(h.events)]
            .filter(Boolean)
            .join(", "),
    found: true,
    mono: h.kind === "ip" || h.kind === "host",
    run: () => openEntity({ kind: h.kind, value: h.value }),
  };
}

// An IPv4 or IPv6 address, or a MAC: what the Proxmox inventory can match (ADR-0045 A6).
const ADDRESS = /^(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9a-fA-F:]*:[0-9a-fA-F:.]+)$/;
const MAC = /^[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}$/;
const LOOKUP_DAYS_MS = 30 * 86_400_000;

/** SQL for "Search events for": the text as one literal, matched in the raw line. The guard
 * still checks it, on a read-only connection. */
function textSql(text: string): string {
  const lit = "'" + text.replace(/'/g, "''") + "'";
  return `SELECT time, source_id, raw\nFROM events\nWHERE contains(raw, ${lit})\nORDER BY time DESC`;
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
  canAsk: canAskProp,
  theme,
  onToggleTheme,
  onClose,
}: CommandPaletteProps) {
  const viewer = useViewer();
  const canAsk = canAskProp ?? viewer.canAsk ?? true;
  const canRunSql = viewer.canRunSql ?? true;
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [recent] = useState(readRecent);
  // Sits under the top bar's search at its width; centered when the bar is not shown.
  const [anchor] = useState(() => {
    const r = document.getElementById("top-search")?.getBoundingClientRect();
    return r && r.width >= 320 ? { left: r.left, width: r.width } : null;
  });
  const askProvider = useAskProvider();
  // Entities (ADR-0038 edit 10): asked of the server once typing pauses, from 2 characters.
  const [typed, setTyped] = useState("");
  useEffect(() => {
    const t = window.setTimeout(() => setTyped(query.trim()), 200);
    return () => window.clearTimeout(t);
  }, [query]);
  const lookup = useQuery({
    queryKey: ["entity-lookup", typed],
    queryFn: () => api.entityLookup(typed),
    enabled: typed.length >= 2,
    staleTime: 30_000,
  });
  // The lookup's own 30 days, fixed per typed value so the cache key does not move.
  const [since] = useState(() => new Date(Date.now() - LOOKUP_DAYS_MS).toISOString());
  const isMac = MAC.test(typed);
  const isIp = !isMac && ADDRESS.test(typed);
  const inventory = useQuery({
    queryKey: ["inventory-matches", [typed], since],
    queryFn: () => api.inventoryMatches([typed], since),
    enabled: isIp || isMac,
    staleTime: 30_000,
  });
  const noIpHit = lookup.isSuccess && !lookup.data.hits.some((h) => h.kind === "ip");
  const coverage = useQuery({
    queryKey: ["address-coverage", typed, since, undefined],
    queryFn: () => api.addressCoverage(typed, since),
    enabled: isIp && noIpHit,
    staleTime: 30_000,
  });
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
    // Logs and Ask AI depend on what the viewer may run, so they are added here and not
    // from the page list. Every tab of a page is listed under Navigate (ADR-0052 3.2).
    if (canRunSql) {
      out.push({
        key: "nav:logs",
        section: "Navigate",
        label: "Logs",
        aliases: ["search", "events", "query", "sql", "filters", "simple search"],
        run: () => navigate("logs"),
      });
    }
    // Closed and Muted are the Alerts Queue's State filter, not tabs, so they have no page
    // of their own in the list above; they stay findable by name.
    for (const [state, label, aliases] of [
      ["closed", "Alerts › Closed", ["closed alerts", "closed"]],
      ["muted", "Alerts › Muted", ["muted alerts", "mutes", "muted"]],
    ] as const)
      out.push({
        key: `nav:alerts:${state}`,
        section: "Navigate",
        label,
        aliases: [...aliases],
        run: () => navigate("alerts", `state=${state}`),
      });
    out.push({
      key: "nav:logs:saved",
      section: "Navigate",
      label: "Logs › Saved searches",
      aliases: ["saved searches", "grimoire"],
      run: () => navigate("saved"),
    });
    // The views of Logs are server-built lists: open to everyone, with or without SQL.
    for (const v of LOGS_VIEWS)
      out.push({
        key: `nav:logs:view:${v.tab}`,
        section: "Navigate",
        label: `Logs › ${v.label}`,
        aliases: v.aliases,
        run: () => navigate("m365", v.tab),
      });
    if (canAsk) {
      out.push({
        key: "nav:ask",
        section: "Navigate",
        label: "Ask AI",
        hint: page === "ask" ? undefined : "Opens beside this page",
        aliases: ["ask", "seance", "question", "ai", "ask in plain english"],
        // On Ask AI, that page; anywhere else, the slide-over (ADR-0042 row 16).
        run: () => (page === "ask" ? navigate("ask") : openAsk()),
      });
    }
    out.push({
      key: "nav:library",
      section: "Navigate",
      label: "Query library",
      hint: "Logs",
      aliases: ["library", "grimoire", "packs", "shipped queries"],
      run: () => {
        seedSearch({ library: true });
        navigate("logs");
      },
    });
    out.push({
      key: "nav:me",
      section: "Navigate",
      label: "Your account and API tokens",
      aliases: ["password", "token", "cli"],
      run: () => navigate("me"),
    });
    if (page === "logs") {
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
        hint: "Open in Logs",
        run: () => {
          seedSearch({ sources: [s.source_id] });
          navigate("logs");
        },
      });
    }
    const text = query.trim();
    if (text.length >= 2) {
      for (const h of lookup.data?.hits ?? []) out.push(hitItem(h));
      for (const m of inventory.data?.matches[typed] ?? []) {
        out.push({
          key: `inventory:${m.source_id}:${m.vmid}`,
          section: "Proxmox inventory",
          label: guestLabel(m),
          hint: m.current ? "Show events" : "Held it earlier; Show events",
          found: true,
          run: () => showGuestEvents(m),
        });
      }
      out.push({
        key: "act:search-text",
        section: "Logs",
        label: `Search events for "${text}"`,
        hint: "Logs, last 7 days",
        found: true,
        run: () => {
          seedSearch({ sql: textSql(text), range: "7d" });
          navigate("logs");
        },
      });
      if (canAsk && text.includes(" ")) {
        // A sentence typed in the palette can be asked straight away (ADR-0042 row 16); a
        // question comes first of everything (owner, 2026-11-03).
        out.push({
          key: "act:ask-text",
          section: looksLikeQuestion(text) ? "Ask AI" : "Logs",
          label: `Ask AI: ${text}`,
          hint: "Opens beside this page",
          found: true,
          run: () => openAsk(text),
        });
      }
    }
    return out;
  }, [
    query,
    lookup.data,
    inventory.data,
    typed,
    isAdmin,
    canAudit,
    canAsk,
    canRunSql,
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
      // Opens under the top bar's search, at its width (ADR-0038 edit 10).
      className={cn(
        "fixed inset-0 z-50 flex items-start bg-black/40 pt-14",
        anchor ? "" : "justify-center px-4",
      )}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        style={anchor ? { marginLeft: anchor.left, width: anchor.width } : undefined}
        className="w-full max-w-[680px] overflow-hidden rounded-card border border-border-strong bg-surface text-text shadow-2xl"
      >
        <div className="flex items-center gap-2 border-b border-border px-3">
          <Search size={16} aria-hidden className="text-text-muted" />
          <input
            autoFocus
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={flat[index] ? optionId(flat[index].key) : undefined}
            aria-label="Search pages, addresses, people, hosts, and AI services"
            placeholder="Type an address, user, host, AI service, or page"
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
        {coverage.data && typed === query.trim() ? (
          <div className="border-b border-border p-2">
            <CoverageLines data={coverage.data} rangeWords="the last 30 days" />
          </div>
        ) : null}
        <div id="palette-list" role="listbox" className="max-h-[60vh] overflow-y-auto py-1">
          {groups.length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-text-muted">Nothing matches</p>
          ) : (
            groups.map((g) => (
              <div key={g.section} role="group" aria-label={g.section}>
                <div className="px-3 pb-1 pt-2 text-xs font-semibold text-text-muted">
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
                          item.section === "Sources" || item.mono ? "font-mono" : "",
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
