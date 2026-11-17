import { useEffect, useId, type FocusEvent, type MouseEvent } from "react";
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
import { useQuery } from "@tanstack/react-query";
import { api, type Overview } from "@/lib/api";
import { useAiInventoryCounts } from "@/features/ai/review";
import { useRailCount } from "@/lib/railCount";
import {
  NO_PROBLEMS,
  healthWords,
  sourceProblems,
  type SourceProblems,
} from "@/features/health/flow";
import { cn } from "@/lib/cn";
import {
  AREAS,
  RAIL_DESCRIPTIONS,
  RAIL_GROUPS,
  SETTINGS_IDS,
  areaOf,
  visibleSettings,
  visibleTabs,
  type AreaTab,
} from "@/lib/nav";
import { tabKey, usePageTabs } from "@/lib/pageTabs";
import { fitTabs, useWindowHeight } from "@/lib/railFit";
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

/** A count that asks for action (fix list 2026-11-16 item 7): one look for every such count,
 * the solid High pair, shown only above zero, beside the label from 1100px. */
function ActionCount({ n, words, data }: { n: number; words: string; data: string }) {
  if (!n) return null;
  return (
    <span
      {...{ [data]: "" }}
      aria-label={words}
      className="ml-auto rounded-badge bg-sev-h-solid px-1.5 font-mono text-xs font-semibold tabular-nums text-sev-h-on md:hidden min-[1100px]:inline"
    >
      {n}
    </span>
  );
}

/** The open alerts the viewer may read, beside Alerts. */
function OpenAlerts() {
  const q = useQuery({ queryKey: ["alerts", "count"], queryFn: api.alertCount });
  const n = q.data?.open ?? 0;
  return <ActionCount n={n} words={`${n} open`} data="data-alert-count" />;
}

/** The Inventory items still to review, beside AI usage; the row then opens the Inventory. */
function AiToReview({ n }: { n: number }) {
  return <ActionCount n={n} words={`${n} to review`} data="data-ai-count" />;
}

/** The viewer's source problems for the Health dot, by the server's one rule: follows the
 * Overview of the Dashboard and Health; elsewhere `/api/health/count`. */
function useHealthProblems(): SourceProblems {
  return (
    useRailCount<
      Overview,
      { not_healthy: number; unhealthy?: number; damaged_files?: number },
      SourceProblems
    >(
      ["overview"],
      api.overview,
      ["health", "count"],
      api.healthCount,
      sourceProblems,
      (c) => ({
        count: c.not_healthy,
        unhealthy: c.unhealthy ?? 0,
        damaged: c.damaged_files ?? 0,
      }),
      NO_PROBLEMS,
    ) ?? NO_PROBLEMS
  );
}

/** Health's dot (ADR-0052 section 3.2): only when something is wrong, in the worst state's
 * color (unhealthy `--danger`, needs attention `--warn`), no number. Its words name the
 * state and the count; they lead the entry's one tooltip and are the link's name. */
function HealthDot({ problems, words }: { problems: SourceProblems; words: string }) {
  if (!problems.count && !problems.damaged) return null;
  return (
    <span
      data-health-dot={problems.unhealthy ? "unhealthy" : "attention"}
      role="img"
      aria-label={words}
      className={cn(
        "ml-auto h-[7px] w-[7px] shrink-0 rounded-[2px] md:absolute md:right-1.5 md:top-1.5 min-[1100px]:static",
        problems.unhealthy ? "bg-danger" : "bg-warn",
      )}
    />
  );
}

/** How long the pointer rests on an entry before its tooltip opens, so passing over the
 * rail does not cover the page; keyboard focus opens it at once. */
export const TIP_DELAY_MS = 150;
let tipTimer: ReturnType<typeof setTimeout> | undefined;

/** Opens a rail entry's tooltip 8px off the rail's right edge. It is fixed, so the rail's
 * own overflow never cuts it, and follows the link, so it is never part of its name. */
function openTip(link: HTMLElement) {
  const tip = link.parentElement?.querySelector<HTMLElement>("[data-rail-tip]");
  if (!tip) return;
  const r = link.getBoundingClientRect();
  const edge = link.closest("#primary-nav")?.getBoundingClientRect().right ?? r.right;
  tip.style.top = `${r.top + r.height / 2}px`;
  tip.style.left = `${edge + 8}px`;
  tip.dataset.open = "";
}

function closeTip(e: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>) {
  clearTimeout(tipTimer);
  delete e.currentTarget.parentElement?.querySelector<HTMLElement>("[data-rail-tip]")?.dataset.open;
}

/** Closes every rail tooltip: a click or a new page moves the entries, and a tooltip is
 * placed only when it opens. */
function closeAllTips() {
  clearTimeout(tipTimer);
  for (const tip of document.querySelectorAll<HTMLElement>("[data-rail-tip][data-open]"))
    delete tip.dataset.open;
}

/** The handlers each rail entry carries for its tooltip. */
const TIP_EVENTS = {
  onMouseEnter: (e: MouseEvent<HTMLElement>) => {
    const link = e.currentTarget;
    clearTimeout(tipTimer);
    tipTimer = setTimeout(() => openTip(link), TIP_DELAY_MS);
  },
  // Keyboard focus only: a click focuses the link too, and its tooltip would then stay
  // over the page it opened.
  onFocus: (e: FocusEvent<HTMLElement>) => {
    clearTimeout(tipTimer);
    if (e.currentTarget.matches(":focus-visible")) openTip(e.currentTarget);
  },
  onMouseLeave: closeTip,
  onBlur: closeTip,
  onClickCapture: closeAllTips,
};

/** A rail entry's one tooltip (D268): its one-line description, shown on hover and keyboard
 * focus from 768px and given as the link's accessible description (`id`), never its name.
 * The icon-only rail has no label on screen, so there it leads with it: "Label: description".
 * A `state` (Health's "Health: 2 sources need attention", already the link's name, D265)
 * leads in its place at every width. */
function RailTip({
  id,
  label,
  text,
  state,
}: {
  id: string;
  label: string;
  text: string;
  state?: string;
}) {
  return (
    <span
      data-rail-tip=""
      role="tooltip"
      className="pointer-events-none fixed z-50 hidden -translate-y-1/2 whitespace-nowrap rounded border border-border-strong bg-surface-head px-2 py-1 text-sm font-normal text-text shadow md:data-[open]:block"
    >
      {state ? (
        <span aria-hidden="true">{state}. </span>
      ) : (
        <span aria-hidden="true" className="min-[1100px]:hidden">
          {label}:{" "}
        </span>
      )}
      <span id={id}>{text}</span>
    </span>
  );
}

/** The current page's tabs under its entry (D268): the page header's list, indented, a
 * smaller step with no icons; the open tab is the current page. None in the icon-only rail. */
function CurrentTabs() {
  const { place, tabs, isOpen, href, onClick } = usePageTabs();
  if (!place || tabs.length < 2) return null;
  return (
    <ul
      aria-label={`${place.area.label} tabs`}
      className="mt-px flex flex-col gap-px md:max-[1099px]:hidden"
    >
      {tabs.map((t) => {
        const on = isOpen(t);
        return (
          <li key={tabKey(t)}>
            <a
              href={href(t)}
              onClick={onClick(t)}
              aria-current={on ? "page" : undefined}
              className={cn(
                "flex h-row-rail-tab items-center rounded pl-9 pr-2.5 text-sm no-underline",
                on
                  ? "font-semibold text-accent-text"
                  : "font-normal text-text-secondary hover:bg-surface-head hover:text-text",
              )}
            >
              {t.label}
            </a>
          </li>
        );
      })}
    </ul>
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

/** The rail (ADR-0052 section 3.2, D268, DESIGN.md 5): pages in three labeled groups, with
 * Health and Settings pinned at the bottom under a hairline at a lower weight, and between
 * them the viewer's Pinned and Recent in regions of their own (D258, D259). Counts that ask
 * for action (open alerts, AI items to review) on the solid High pair; Health a status dot
 * only. The current page lists its own tabs under it; nothing else expands. Each entry has a
 * one-line description as its tooltip. An entry the viewer cannot open is not shown. 208px
 * from 1100px; between 768 and 1100px icons only, with the label in the tooltip; on phones it
 * opens from the Menu button. */
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
  const aiReview = useAiInventoryCounts()?.toReview ?? 0;
  const problems = useHealthProblems();
  const healthSays = healthWords(problems);
  const tipId = useId();
  const pageTabs = usePageTabs();
  // Tab rows the current page shows, which Pinned and Recent make room for on short windows;
  // the last to give way, after them (the page's own tab bar keeps them).
  const tabRows = fitTabs(useWindowHeight(), pageTabs.tabs.length > 1 ? pageTabs.tabs.length : 0);
  useEffect(closeAllTips, [active, activeTab]);

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
    const tip = `${tipId}-${row.key}`;
    // The current entry with its tabs open is the current section; its open tab the page.
    const expanded = row.current && tabRows > 0;
    return (
      <li key={row.key}>
        <a
          href={pathFor(row.to.page, row.to.tab)}
          onClick={go(row.to.page, row.to.tab)}
          {...TIP_EVENTS}
          aria-current={row.current ? (expanded ? "true" : "page") : undefined}
          // Health with a dot: its words are the link's name, so the state is never color only.
          aria-label={row.key === "health" && healthSays ? healthSays : undefined}
          aria-describedby={tip}
          data-rail-entry={row.key}
          className={rowClass(row.current, row.pinned)}
        >
          <Icon size={16} aria-hidden className="shrink-0" />
          <span className="md:sr-only min-[1100px]:not-sr-only">{row.label}</span>
          {row.key === "alerts" ? <OpenAlerts /> : null}
          {row.key === "ai" ? <AiToReview n={aiReview} /> : null}
          {row.key === "health" && healthSays ? (
            <HealthDot problems={problems} words={healthSays} />
          ) : null}
        </a>
        <RailTip
          id={tip}
          label={row.label}
          text={RAIL_DESCRIPTIONS[row.key] ?? row.label}
          state={row.key === "health" ? healthSays || undefined : undefined}
        />
        {row.current && tabRows ? <CurrentTabs /> : null}
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
                  {...TIP_EVENTS}
                  aria-current={inSettings ? "page" : undefined}
                  aria-describedby={`${tipId}-settings`}
                  data-rail-entry="settings"
                  className={rowClass(inSettings, true)}
                >
                  <Settings size={16} aria-hidden className="shrink-0" />
                  <span className="md:sr-only min-[1100px]:not-sr-only">Settings</span>
                </a>
                {/* Settings keeps its own sub-nav on its pages (D70), so it never expands. */}
                <RailTip
                  id={`${tipId}-settings`}
                  label="Settings"
                  text={RAIL_DESCRIPTIONS.settings ?? "Settings"}
                />
              </li>
            ) : null}
          </ul>
        ) : null}
      </nav>
      {/* Pinned saved searches and dashboards, then Recent (D258, D259). */}
      <div className="col-start-1 row-start-2 min-w-0">
        <PinnedNav tabRows={tabRows} />
        <RecentNav tabRows={tabRows} />
      </div>
    </div>
  );
}
