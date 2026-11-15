import { useEffect, useState, useSyncExternalStore, type MouseEvent } from "react";
import {
  Activity,
  Bell,
  Cpu,
  LayoutGrid,
  MessageCircleQuestion,
  Search,
  Settings,
  SquareTerminal,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AiInventory, type Overview } from "@/lib/api";
import { toReview } from "@/features/ai/review";
import { needingAttention } from "@/features/health/flow";
import { cn } from "@/lib/cn";
import {
  AREAS,
  RAIL_GROUPS,
  SETTINGS_IDS,
  areaOf,
  visibleSettings,
  visibleTabs,
  type AreaTab,
} from "@/lib/nav";
import { navigate, pathFor, type PageId } from "@/lib/route";
import { useViewer } from "@/lib/viewer";
import { PinnedNav } from "./PinnedNav";
import { RecentNav } from "./RecentNav";

interface SideNavProps {
  active: string;
  /** The open tab of the active page, "" for its first. */
  activeTab: string;
  isAdmin: boolean;
  canAudit: boolean;
  /** Defaults to the viewer's: Auditors have no Ask unless the Auditor SQL setting is on (D220). */
  canAsk?: boolean;
  /** Narrow screens only: shown when the top bar's Menu button is pressed. */
  open?: boolean;
}

function go(page: PageId | undefined, tab?: string) {
  return (e: MouseEvent) => {
    if (!page || e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    navigate(page, tab);
  };
}

const ICONS: Record<string, LucideIcon> = {
  dashboard: LayoutGrid,
  alerts: Bell,
  logs: Search,
  ask: MessageCircleQuestion,
  people: Users,
  ai: Cpu,
  agents: SquareTerminal,
  health: Activity,
};

/** Where you are (DESIGN.md 5): a 2px bar in the accent text color on the row's left edge
 * and the label in that color at 600. No fill. The bar is a shape and the weight changes,
 * so color is never the only cue. */
function rowClass(current: boolean, pinned: boolean): string {
  return cn(
    "relative flex h-row-rail items-center gap-2.5 rounded px-2.5 text-base no-underline",
    current
      ? "font-semibold text-accent-text before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:rounded-full before:bg-accent-text"
      : cn(
          "text-text-secondary hover:bg-surface-head hover:text-text",
          pinned ? "font-normal" : "font-medium",
        ),
  );
}

/** The open alerts the viewer may read, beside Alerts, on the solid High pair. */
function OpenAlerts() {
  const q = useQuery({ queryKey: ["alerts", "count"], queryFn: api.alertCount });
  const n = q.data?.open ?? 0;
  if (!n) return null;
  return (
    <span
      aria-label={`${n} open`}
      className="ml-auto rounded-badge bg-sev-h-solid px-1.5 font-mono text-xs font-semibold tabular-nums text-sev-h-on md:hidden min-[1100px]:inline"
    >
      {n}
    </span>
  );
}

// A count's first read waits until the page's own requests are out.
const FIRST_READ_MS = 2500;
const EVERY_MS = 300_000;
/** A page answer this recent is the count's answer; the pages refresh theirs themselves. */
const PAGE_FRESH_MS = 90_000;

/** A rail count that follows a page's own data (`pageKey`) while a page shows it, and
 * asks for nothing then. On other pages it asks a numbers-only count every five minutes,
 * so it can be up to five minutes behind there. Never loads the page's data itself. Keep
 * `countKey` under `pageKey`: a change that invalidates the page's data then refreshes the
 * count at once, and page data so invalidated is never the answer. */
function useRailCount<P, C>(
  pageKey: string[],
  pageFn: () => Promise<P>,
  countKey: string[],
  countFn: () => Promise<C>,
  fromPage: (p: P) => number,
  fromCount: (c: C) => number,
): number {
  const page = useQuery({ queryKey: pageKey, queryFn: pageFn, enabled: false });
  const client = useQueryClient();
  const invalidated = useSyncExternalStore(
    (cb) => client.getQueryCache().subscribe(cb),
    () => client.getQueryState(pageKey)?.isInvalidated ?? false,
  );
  const [now, setNow] = useState(() => Date.now());
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const first = window.setTimeout(() => setReady(true), FIRST_READ_MS);
    const tick = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(tick);
    };
  }, []);
  const usable = page.data !== undefined && !invalidated;
  const pageFresh = usable && now - page.dataUpdatedAt < PAGE_FRESH_MS;
  const count = useQuery({
    queryKey: countKey,
    queryFn: countFn,
    // Not while a page is loading or has just loaded the same answer.
    enabled: ready && !page.isFetching && !pageFresh,
    refetchInterval: EVERY_MS,
    staleTime: 60_000,
  });
  // Whichever answer is newer: the page's or the count.
  if (usable && page.data !== undefined && page.dataUpdatedAt >= count.dataUpdatedAt)
    return fromPage(page.data);
  return count.data === undefined ? 0 : fromCount(count.data);
}

/** Outlined counts (D258): shown only above zero, beside the label from 1100px. */
const OUTLINED = "ml-auto rounded-badge border px-1.5 font-mono text-xs tabular-nums";

/** The Inventory's items still to review, for AI usage's count: follows the Inventory a
 * page loaded; elsewhere `/api/ai/inventory/count`, which is not audited. Both keys sit
 * under ["ai-usage"], which every review invalidates (AI usage, AI settings, Alerts). */
function useAiToReview(): number {
  return useRailCount<AiInventory, { to_review: number }>(
    ["ai-usage", "inventory"],
    () => api.aiInventory(30),
    ["ai-usage", "inventory", "count"],
    api.aiInventoryCount,
    (p) => toReview(p.items),
    (c) => c.to_review,
  );
}

interface CountProps {
  n: number;
}

/** Beside AI usage, outlined and neutral; the row then opens the Inventory. */
function AiToReview({ n }: CountProps) {
  if (!n) return null;
  return (
    <span
      data-ai-count=""
      aria-label={`${n} to review`}
      className={cn(
        OUTLINED,
        "border-border-strong text-text-secondary md:hidden min-[1100px]:inline",
      )}
    >
      {n}
    </span>
  );
}

/** Beside Health: how many of the viewer's sources need attention, outlined in warn; its
 * words for screen readers and as the tooltip. Nothing when all is well or nothing is
 * known. Follows the Overview of the Dashboard and Health; elsewhere `/api/health/count`. */
function HealthCount() {
  const n = useRailCount<Overview, { not_healthy: number }>(
    ["overview"],
    api.overview,
    ["health", "count"],
    api.healthCount,
    needingAttention,
    (c) => c.not_healthy,
  );
  if (!n) return null;
  const words = `${n} ${n === 1 ? "source needs" : "sources need"} attention`;
  return (
    <span
      data-health-count=""
      title={words}
      className={cn(
        OUTLINED,
        "border-warn text-warn md:absolute md:right-0.5 md:top-0.5 min-[1100px]:static",
      )}
    >
      <span aria-hidden>{n}</span>
      <span className="sr-only">{words}</span>
    </span>
  );
}

interface Row {
  key: string;
  label: string;
  icon: LucideIcon;
  /** Where the row goes: the first tab the viewer may open. */
  to: AreaTab;
  current: boolean;
  pinned: boolean;
}

/** The rail (ADR-0052 section 3.2, DESIGN.md 5): pages only, in three labeled groups, with
 * Health and Settings pinned at the bottom under a hairline at a lower weight, and between
 * them the viewer's Recent entities in a region of its own (D258). Counts: open alerts
 * solid, AI items to review outlined, sources needing attention outlined in warn. No entry has
 * children and nothing collapses; a page's tabs are in its header. An entry the viewer
 * cannot open is not shown. 208px from 1100px; between 768 and 1100px icons only, with the
 * label as the tooltip; on phones it opens from the Menu button. */
export function SideNav({
  active,
  activeTab,
  isAdmin,
  canAudit,
  canAsk: canAskProp,
  open = false,
}: SideNavProps) {
  const viewer = useViewer();
  const canAsk = canAskProp ?? viewer.canAsk ?? true;
  const canRunSql = viewer.canRunSql ?? true;
  const settings = visibleSettings(isAdmin, canAudit);
  // Settings opens on Sources, the page used most; the checklist is first in its list.
  const items = settings.flatMap((g) => g.items);
  const firstSetting = (items.find((i) => i.id === "sources") ?? items[0])?.page;
  const inSettings = SETTINGS_IDS.has(active);
  const place = areaOf(active as PageId, activeTab);
  const aiReview = useAiToReview();

  const rowsOf = (ids: string[], pinned: boolean): Row[] =>
    ids.flatMap((id): Row[] => {
      const area = AREAS.find((a) => a.id === id);
      const tabs = area ? visibleTabs(area, isAdmin, canAsk, canRunSql) : [];
      // With something to review AI usage opens its Inventory, as the Dashboard's tile does.
      const review = id === "ai" && aiReview ? tabs.find((t) => t.tab === "inventory") : undefined;
      const first = review ?? tabs[0];
      if (!area || !first) return [];
      return [
        {
          key: area.id,
          label: area.label,
          icon: ICONS[area.id] ?? LayoutGrid,
          to: first,
          current: place?.area.id === area.id,
          pinned,
        },
      ];
    });

  const link = (row: Row) => {
    const Icon = row.icon;
    return (
      <li key={row.key}>
        <a
          href={pathFor(row.to.page, row.to.tab)}
          onClick={go(row.to.page, row.to.tab)}
          aria-current={row.current ? "page" : undefined}
          title={row.label}
          className={rowClass(row.current, row.pinned)}
        >
          <Icon size={16} aria-hidden className="shrink-0" />
          <span className="md:sr-only min-[1100px]:not-sr-only">{row.label}</span>
          {row.key === "alerts" ? <OpenAlerts /> : null}
          {row.key === "ai" ? <AiToReview n={aiReview} /> : null}
          {row.key === "health" ? <HealthCount /> : null}
        </a>
      </li>
    );
  };

  const groups = RAIL_GROUPS.filter((g) => !g.pinned)
    .map((g) => ({ group: g, rows: rowsOf(g.areas, false) }))
    .filter((g) => g.rows.length > 0);
  const pinned = RAIL_GROUPS.filter((g) => g.pinned).flatMap((g) => rowsOf(g.areas, true));

  return (
    // The rail is a grid of four rows: the page groups, Recent, the space left, and Health
    // and Settings. The Primary nav spans them all on a subgrid, so Recent sits between its
    // groups and its bottom cluster as a region of its own (D258), never one of its links.
    <div
      id="primary-nav"
      className={cn(
        // From md up the rail stays in view under the top bar; it fits without scrolling.
        "w-full shrink-0 grid-cols-1 grid-rows-[auto_auto_1fr_auto] border-b border-border bg-nav px-2 py-3 md:sticky md:top-12 md:h-[calc(100dvh-3rem)] md:w-14 md:self-start md:overflow-y-auto md:border-b-0 md:border-r min-[1100px]:w-52",
        open ? "grid" : "hidden md:grid",
      )}
    >
      <nav aria-label="Primary" className="col-start-1 row-span-full grid grid-rows-subgrid">
        <div>
          {groups.map(({ group, rows }) => (
            <section key={group.id} aria-label={group.label} className="mb-3">
              {/* Group labels show where the row labels do: on phones and from 1100px. */}
              <div
                aria-hidden="true"
                className="px-2.5 pb-1 text-xs text-text-muted md:hidden min-[1100px]:block"
              >
                {group.label}
              </div>
              <ul className="flex flex-col gap-px">{rows.map(link)}</ul>
            </section>
          ))}
        </div>
        {pinned.length || firstSetting ? (
          <ul
            aria-label="Health and settings"
            className="row-start-4 flex flex-col gap-px border-t border-border pt-2"
          >
            {pinned.map(link)}
            {firstSetting ? (
              <li>
                <a
                  href={pathFor(firstSetting)}
                  onClick={go(firstSetting)}
                  aria-current={inSettings ? "page" : undefined}
                  title="Settings"
                  className={rowClass(inSettings, true)}
                >
                  <Settings size={16} aria-hidden className="shrink-0" />
                  <span className="md:sr-only min-[1100px]:not-sr-only">Settings</span>
                </a>
              </li>
            ) : null}
          </ul>
        ) : null}
      </nav>
      {/* Pinned saved searches and dashboards, then Recent (D258, D259). */}
      <div className="col-start-1 row-start-2 min-w-0">
        <PinnedNav />
        <RecentNav />
      </div>
    </div>
  );
}
