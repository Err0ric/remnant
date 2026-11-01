import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import {
  Activity,
  Bell,
  BookMarked,
  ChevronDown,
  Cpu,
  Grid2x2,
  LayoutGrid,
  Search,
  Settings,
  SquareTerminal,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import {
  AREAS,
  RAIL_GROUPS,
  SETTINGS_IDS,
  areaOf,
  visibleSettings,
  visibleTabs,
  type Area,
  type AreaTab,
} from "@/lib/nav";
import { navigate, pathFor, type PageId } from "@/lib/route";

interface SideNavProps {
  active: string;
  /** The open tab of the active page, "" for its first. */
  activeTab: string;
  isAdmin: boolean;
  canAudit: boolean;
  /** Narrow screens only: shown when the top bar's Menu button is pressed. */
  open?: boolean;
}

const COLLAPSED_KEY = "app.rail.collapsed";
// Groups whose folded-by-default state was already applied in this browser, so a group
// that starts folded (Connected apps, System) does so once, and the viewer's own choice
// holds from then on.
const DEFAULTS_KEY = "app.rail.defaults";

function strings(raw: string | null): string[] {
  const v: unknown = JSON.parse(raw ?? "[]");
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

/** Areas whose sub-pages start folded (owner, 2026-10-31): Alerts shows its open count on
 * its own row, so its pages can stay out of the way. Stored as "area:<id>". */
const FOLDED_AREAS = ["alerts"];

function readCollapsed(): string[] {
  const folded = [
    ...RAIL_GROUPS.filter((g) => g.collapsedByDefault).map((g) => g.id),
    ...FOLDED_AREAS.map((a) => `area:${a}`),
  ];
  try {
    const collapsed = strings(window.localStorage.getItem(COLLAPSED_KEY));
    const applied = strings(window.localStorage.getItem(DEFAULTS_KEY));
    const fresh = folded.filter((id) => !applied.includes(id));
    if (!fresh.length) return collapsed;
    const next = [...new Set([...collapsed, ...fresh])];
    window.localStorage.setItem(DEFAULTS_KEY, JSON.stringify([...applied, ...fresh]));
    window.localStorage.setItem(COLLAPSED_KEY, JSON.stringify(next));
    return next;
  } catch {
    return folded;
  }
}

function writeCollapsed(ids: string[]): void {
  try {
    window.localStorage.setItem(COLLAPSED_KEY, JSON.stringify(ids));
  } catch {
    // Storage can be unavailable; the choice holds for this page view.
  }
}

function go(page: PageId | undefined, tab?: string) {
  return (e: MouseEvent) => {
    if (!page || e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    navigate(page, tab);
  };
}

/** A page row: 32px, 15px; the current page on the accent tint. */
function pageClass(current: boolean): string {
  return cn(
    "flex min-h-[32px] items-center gap-2.5 rounded px-2.5 text-md no-underline",
    current
      ? "bg-accent-subtle text-accent-text"
      : "text-text-secondary hover:bg-surface-head hover:text-text",
  );
}

/** The open alerts the viewer may read, beside Alerts (ADR-0037 row 2). */
function OpenAlerts() {
  const q = useQuery({ queryKey: ["alerts", "open"], queryFn: () => api.alerts("open") });
  const n = q.data?.open ?? 0;
  if (!n) return null;
  return (
    <span
      aria-label={`${n} open`}
      className="ml-auto rounded bg-accent-subtle px-1.5 font-mono text-xs tabular-nums text-accent-text md:hidden min-[1100px]:inline"
    >
      {n}
    </span>
  );
}

const ICONS: Record<string, LucideIcon> = {
  dashboard: LayoutGrid,
  alerts: Bell,
  investigate: Search,
  ai: Cpu,
  agents: SquareTerminal,
  m365: Grid2x2,
  health: Activity,
  "page:search": Search,
  "page:investigate": Users,
  "page:saved": BookMarked,
};

interface Row {
  key: string;
  label: string;
  icon: LucideIcon;
  /** Where the row goes: the first tab. */
  to: AreaTab;
  /** Sub-pages listed under the row; empty for a single page. */
  subs: AreaTab[];
  current: boolean;
  alerts?: boolean;
}

/** The rows of a group: one per area, or one per tab when the area is the group itself
 * (Investigate lists Search, People & devices, and Saved searches as pages). */
function rowsOf(
  areas: Area[],
  flatten: boolean,
  isAdmin: boolean,
  place: ReturnType<typeof areaOf>,
): Row[] {
  return areas.flatMap((area): Row[] => {
    const tabs = visibleTabs(area, isAdmin);
    const first = tabs[0];
    if (!first) return [];
    if (flatten && tabs.length > 1) {
      return tabs.map((t) => ({
        key: `${t.page}:${t.tab ?? ""}`,
        label: t.label,
        icon: ICONS[`page:${t.page}`] ?? ICONS[area.id] ?? LayoutGrid,
        to: t,
        subs: [],
        current: place?.tab === t,
      }));
    }
    return [
      {
        key: area.id,
        label: area.label,
        icon: ICONS[area.id] ?? LayoutGrid,
        to: first,
        subs: tabs.length > 1 ? tabs : [],
        current: place?.area.id === area.id,
        alerts: area.id === "alerts",
      },
    ];
  });
}

/** The main rail (ADR-0038 edit 10, owner 2026-10-31): five collapsible groups, every page
 * with its sub-pages listed under it, the current one highlighted. Connected apps and
 * System start folded; each group's open or closed state is remembered in this browser. A
 * folded group shows its pages in a flyout on hover or focus. Between 768 and 1100px the
 * rail shows icons, and a page's sub-pages open on hover or focus. */
export function SideNav({ active, activeTab, isAdmin, canAudit, open = false }: SideNavProps) {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const settings = visibleSettings(isAdmin, canAudit);
  // Settings opens on Sources, the page used most; the checklist is first in its list.
  const items = settings.flatMap((g) => g.items);
  const firstSetting = (items.find((i) => i.id === "sources") ?? items[0])?.page;
  const inSettings = SETTINGS_IDS.has(active);
  const place = areaOf(active as PageId, activeTab);

  // A folded group's pages, in one flyout beside its header. Fixed, so the rail's own
  // scrolling never clips it.
  const [fly, setFly] = useState<{ id: string; top: number; left: number } | null>(null);
  const closing = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(closing.current), []);
  const keep = () => window.clearTimeout(closing.current);
  // Keep the flyout on screen: a group near the bottom opens upwards as far as needed.
  const flyBox = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = flyBox.current;
    if (!fly || !el) return;
    const room = window.innerHeight - 8;
    const h = el.getBoundingClientRect().height;
    if (fly.top + h > room) {
      const top = Math.max(8, room - h);
      if (top !== fly.top) setFly({ ...fly, top });
    }
  }, [fly]);
  const leave = () => {
    keep();
    closing.current = window.setTimeout(() => setFly(null), 150);
  };
  // `force`: the icon rail (768 to 1100px) shows an area's sub-pages on hover even when
  // the area is not folded. The flyout is fixed and starts at the rail's right edge, so
  // the rail's scrolling never clips it and it never covers the rail (owner, 2026-11-01).
  const showGroup = (id: string, el: HTMLElement, force = false) => {
    keep();
    if (!force && !collapsed.includes(id)) return;
    const r = el.getBoundingClientRect();
    const rail = el.closest("nav")?.getBoundingClientRect();
    setFly({ id, top: r.top, left: rail ? rail.right : r.right });
  };
  const iconRail = () =>
    window.matchMedia?.("(min-width: 768px) and (max-width: 1099.98px)").matches ?? false;

  const toggle = (id: string) => {
    setFly(null);
    const next = collapsed.includes(id) ? collapsed.filter((x) => x !== id) : [...collapsed, id];
    setCollapsed(next);
    writeCollapsed(next);
  };

  const subList = (row: Row, cls: string, label: string) => (
    <ul aria-label={label} className={cls}>
      {row.subs.map((t) => {
        const current = row.current && place?.tab === t;
        return (
          <li key={`${t.page}:${t.tab ?? ""}`}>
            <a
              href={pathFor(t.page, t.tab)}
              onClick={go(t.page, t.tab)}
              aria-current={current ? "page" : undefined}
              className={cn(
                "flex min-h-[26px] items-center whitespace-nowrap rounded px-2.5 text-base no-underline",
                current
                  ? "bg-accent-subtle font-semibold text-accent-text"
                  : "text-text-secondary hover:bg-surface-head hover:text-text",
              )}
            >
              {t.label}
            </a>
          </li>
        );
      })}
    </ul>
  );

  return (
    <nav
      id="primary-nav"
      aria-label="Primary"
      className={cn(
        // From md up the rail stays in view under the top bar and scrolls on its own.
        "w-full shrink-0 border-b border-border bg-nav px-2 py-3 md:sticky md:top-12 md:h-[calc(100dvh-3rem)] md:w-14 md:self-start md:overflow-y-auto md:border-b-0 md:border-r min-[1100px]:w-60 min-[1100px]:px-3",
        open ? "block" : "hidden md:block",
      )}
    >
      {RAIL_GROUPS.map((group) => {
        const areas = group.areas
          .map((id) => AREAS.find((a) => a.id === id))
          .filter((a): a is Area => Boolean(a));
        const rows = rowsOf(areas, Boolean(group.flatten), isAdmin, place);
        const withSettings = group.settings && firstSetting;
        if (!rows.length && !withSettings) return null;
        const shut = collapsed.includes(group.id);
        const listId = `rail-${group.id}`;
        return (
          <section
            key={group.id}
            aria-label={group.label}
            className="mb-2 border-b border-border pb-2 last:mb-0 last:border-b-0 md:mb-1 md:pb-1 min-[1100px]:mb-3 min-[1100px]:pb-3"
          >
            {/* Group headers show with labels: on phones and from 1100px. */}
            <button
              type="button"
              onMouseEnter={(e) => showGroup(group.id, e.currentTarget)}
              onMouseLeave={leave}
              onFocus={(e) => showGroup(group.id, e.currentTarget)}
              onKeyDown={(e) => {
                if (e.key === "Escape") setFly(null);
              }}
              aria-haspopup={shut ? "true" : undefined}
              onClick={() => toggle(group.id)}
              aria-expanded={!shut}
              aria-label={`${group.label} group`}
              aria-controls={listId}
              className="flex w-full items-center justify-between rounded px-2.5 py-1 text-sm font-semibold text-text-muted hover:text-text md:hidden min-[1100px]:flex"
            >
              {group.label}
              <ChevronDown
                size={16}
                aria-hidden
                className={cn(
                  "transition-transform motion-reduce:transition-none",
                  shut && "-rotate-90",
                )}
              />
            </button>
            {/* Collapsing applies where the group header shows; the icon rail lists all. */}
            <ul id={listId} className={cn("mt-0.5", shut && "hidden md:block min-[1100px]:hidden")}>
              {rows.map((row) => {
                const Icon = row.icon;
                const areaKey = `area:${row.key}`;
                const areaShut = row.subs.length > 0 && collapsed.includes(areaKey);
                return (
                  <li
                    key={row.key}
                    className="group relative"
                    onMouseEnter={(e) => {
                      if (areaShut) showGroup(areaKey, e.currentTarget);
                      else if (row.subs.length && iconRail())
                        showGroup(areaKey, e.currentTarget, true);
                    }}
                    onFocus={(e) => {
                      if (row.subs.length && iconRail()) showGroup(areaKey, e.currentTarget, true);
                    }}
                    onMouseLeave={row.subs.length ? leave : undefined}
                  >
                    <a
                      href={pathFor(row.to.page, row.to.tab)}
                      onClick={go(row.to.page, row.to.tab)}
                      aria-current={row.current ? (row.subs.length ? "true" : "page") : undefined}
                      title={row.label}
                      className={cn(
                        row.subs.length && "min-[1100px]:pr-8",
                        row.subs.length && row.current
                          ? // The sub-page carries the highlight; the icon rail shows it here.
                            cn(
                              pageClass(false),
                              "text-text md:bg-accent-subtle md:text-accent-text min-[1100px]:bg-transparent min-[1100px]:text-text",
                            )
                          : pageClass(row.current),
                      )}
                    >
                      <Icon size={18} aria-hidden className="shrink-0" />
                      <span className="md:sr-only min-[1100px]:not-sr-only">{row.label}</span>
                      {row.alerts ? <OpenAlerts /> : null}
                    </a>
                    {row.subs.length ? (
                      // Fold an area's sub-pages (labelled rail only); remembered like groups.
                      <button
                        type="button"
                        onClick={() => toggle(areaKey)}
                        aria-expanded={!areaShut}
                        aria-label={`${row.label} sub-pages`}
                        className="absolute right-1 top-1.5 hidden size-5 items-center justify-center rounded text-text-muted hover:text-text min-[1100px]:flex"
                      >
                        <ChevronDown
                          size={14}
                          aria-hidden
                          className={cn(
                            "transition-transform motion-reduce:transition-none",
                            areaShut && "-rotate-90",
                          )}
                        />
                      </button>
                    ) : null}
                    {row.subs.length
                      ? subList(
                          row,
                          cn(
                            "mb-1 ml-[19px] mt-0.5 border-l border-border pl-2 md:hidden",
                            !areaShut && "min-[1100px]:block",
                          ),
                          `${row.label} pages`,
                        )
                      : null}
                  </li>
                );
              })}
              {withSettings ? (
                <li>
                  <a
                    href={pathFor(firstSetting)}
                    onClick={go(firstSetting)}
                    aria-current={inSettings ? "page" : undefined}
                    title="Settings"
                    className={pageClass(inSettings)}
                  >
                    <Settings size={18} aria-hidden className="shrink-0" />
                    <span className="md:sr-only min-[1100px]:not-sr-only">Settings</span>
                  </a>
                </li>
              ) : null}
            </ul>
          </section>
        );
      })}
      {fly ? groupFlyout() : null}
    </nav>
  );

  function groupFlyout() {
    if (!fly) return null;
    const area = fly.id.startsWith("area:") ? AREAS.find((a) => `area:${a.id}` === fly.id) : null;
    const group = area
      ? { id: fly.id, label: area.label, areas: [area.id], settings: false, flatten: false }
      : RAIL_GROUPS.find((g) => g.id === fly.id);
    if (!group) return null;
    const areas = group.areas
      .map((id) => AREAS.find((a) => a.id === id))
      .filter((a): a is Area => Boolean(a));
    const rows = rowsOf(areas, Boolean(group.flatten), isAdmin, place);
    return (
      <div
        ref={flyBox}
        role="presentation"
        onMouseEnter={keep}
        onMouseLeave={leave}
        onClick={() => setFly(null)}
        style={{ top: fly.top, left: fly.left }}
        className="fixed z-50 hidden pl-2 md:block"
      >
        <div
          aria-label={`${group.label} pages`}
          className="min-w-48 rounded-card border border-border bg-surface p-1.5 shadow-lg"
        >
          {area ? null : (
            <div className="px-2.5 py-1 text-sm font-semibold text-text-muted">{group.label}</div>
          )}
          <ul>
            {rows.map((row) => (
              <li key={row.key}>
                <a
                  href={pathFor(row.to.page, row.to.tab)}
                  onClick={go(row.to.page, row.to.tab)}
                  className={pageClass(row.current && !row.subs.length)}
                >
                  {row.label}
                </a>
                {row.subs.length
                  ? subList(
                      row,
                      "ml-2.5 border-l border-border pl-2",
                      `${row.label} pages, ${group.label} menu`,
                    )
                  : null}
              </li>
            ))}
            {group.settings && firstSetting ? (
              <li>
                <a
                  href={pathFor(firstSetting)}
                  onClick={go(firstSetting)}
                  className={pageClass(inSettings)}
                >
                  Settings
                </a>
              </li>
            ) : null}
          </ul>
        </div>
      </div>
    );
  }
}
