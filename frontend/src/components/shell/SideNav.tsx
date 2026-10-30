import type { MouseEvent } from "react";
import {
  Activity,
  Bell,
  Cpu,
  Grid2x2,
  LayoutGrid,
  Search,
  Settings,
  SquareTerminal,
  type LucideIcon,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { AREAS, SETTINGS_IDS, areaOf, visibleSettings, visibleTabs } from "@/lib/nav";
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

function go(page: PageId | undefined, tab?: string) {
  return (e: MouseEvent) => {
    if (!page || e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    navigate(page, tab);
  };
}

function itemClass(current: boolean): string {
  return cn(
    "flex items-center gap-2.5 rounded px-2.5 py-1.5 text-base font-semibold no-underline",
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
      className="ml-auto rounded bg-accent-subtle md:hidden min-[1100px]:inline px-1.5 font-mono text-xs tabular-nums text-accent-text"
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
};

/** The main rail: one row per area (ADR-0038), then Settings pinned to the foot. Below
 * 1100px the rail shows icons, with the label as a tooltip. */
export function SideNav({ active, activeTab, isAdmin, canAudit, open = false }: SideNavProps) {
  const settings = visibleSettings(isAdmin, canAudit);
  // Settings opens on Sources, the page used most; the checklist is first in its list.
  const items = settings.flatMap((g) => g.items);
  const first = (items.find((i) => i.id === "sources") ?? items[0])?.page;
  const inSettings = SETTINGS_IDS.has(active);
  const here = areaOf(active as PageId, activeTab)?.area.id;
  return (
    <nav
      id="primary-nav"
      aria-label="Primary"
      className={cn(
        // From md up the rail stays in view under the top bar, with Settings pinned to its foot.
        "w-full shrink-0 border-b border-border bg-nav px-2 py-3 md:sticky md:top-12 md:flex md:h-[calc(100dvh-3rem)] md:w-14 md:flex-col md:self-start md:border-b-0 md:border-r min-[1100px]:w-50",
        open ? "block" : "hidden",
      )}
    >
      <ul className="md:min-h-0 md:flex-1 md:overflow-y-auto">
        {AREAS.map((area) => {
          const tab = visibleTabs(area, isAdmin)[0];
          if (!tab) return null;
          const Icon = ICONS[area.id] ?? LayoutGrid;
          return (
            <li key={area.id}>
              <a
                href={pathFor(tab.page, tab.tab)}
                onClick={go(tab.page, tab.tab)}
                aria-current={here === area.id ? "page" : undefined}
                title={area.label}
                className={itemClass(here === area.id)}
              >
                <Icon size={16} aria-hidden className="shrink-0" />
                <span className="md:sr-only min-[1100px]:not-sr-only">{area.label}</span>
                {area.id === "alerts" ? <OpenAlerts /> : null}
              </a>
            </li>
          );
        })}
      </ul>
      {first ? (
        <div className="shrink-0 border-t border-border pt-3">
          <a
            href={pathFor(first)}
            onClick={go(first)}
            aria-current={inSettings ? "page" : undefined}
            title="Settings"
            className={itemClass(inSettings)}
          >
            <Settings size={16} aria-hidden className="shrink-0" />
            <span className="md:sr-only min-[1100px]:not-sr-only">Settings</span>
          </a>
        </div>
      ) : null}
    </nav>
  );
}
