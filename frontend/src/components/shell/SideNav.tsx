import type { MouseEvent } from "react";
import { cn } from "@/lib/cn";
import { NAV_GROUPS as GROUPS, SETTINGS_IDS, visibleSettings, type NavItem } from "@/lib/nav";
import { navigate, pathFor, type PageId } from "@/lib/route";

interface SideNavProps {
  active: string;
  isAdmin: boolean;
  canAudit: boolean;
  /** Narrow screens only: shown when the top bar's Menu button is pressed. */
  open?: boolean;
}

function go(page: PageId | undefined) {
  return (e: MouseEvent) => {
    if (!page || e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    navigate(page);
  };
}

function itemClass(current: boolean, ready: boolean): string {
  return cn(
    "flex items-center rounded px-2.5 py-1.5 text-base no-underline",
    current
      ? "bg-accent-subtle font-semibold text-accent-text"
      : ready
        ? "text-text hover:bg-surface-head"
        : "cursor-default text-text-muted",
  );
}

function Item({ item, active }: { item: NavItem; active: string }) {
  return (
    <a
      href={item.page ? pathFor(item.page) : undefined}
      onClick={go(item.page)}
      aria-current={item.id === active ? "page" : undefined}
      aria-disabled={item.ready ? undefined : true}
      title={item.ready ? undefined : "Coming in a later release"}
      className={itemClass(item.id === active, item.ready)}
    >
      {item.ready ? (
        item.label
      ) : (
        <>
          <span>{item.label}</span>
          {/* Visible without hovering: these look like links otherwise. */}
          <span className="ml-auto text-xs text-text-muted">Later</span>
        </>
      )}
    </a>
  );
}

/** The main rail: daily work, then one Settings entry that opens the settings area. */
export function SideNav({ active, isAdmin, canAudit, open = false }: SideNavProps) {
  const settings = visibleSettings(isAdmin, canAudit);
  const first = settings[0]?.items[0]?.page;
  const inSettings = SETTINGS_IDS.has(active);
  return (
    <nav
      id="primary-nav"
      aria-label="Primary"
      className={cn(
        "w-full shrink-0 border-b border-border bg-nav px-2 py-3 md:block md:w-55 md:border-b-0 md:border-r",
        open ? "block" : "hidden",
      )}
    >
      {GROUPS.map((group) => (
        <div key={group.label} className="mb-3">
          <div className="px-2.5 py-1 text-xs text-text-muted">{group.label}</div>
          {group.items
            .filter((item) => (isAdmin || !item.adminOnly) && (canAudit || !item.auditOnly))
            .map((item) => (
              <Item key={item.id} item={item} active={active} />
            ))}
        </div>
      ))}
      {first ? (
        <div className="border-t border-border pt-3">
          <a
            href={pathFor(first)}
            onClick={go(first)}
            aria-current={inSettings ? "page" : undefined}
            className={itemClass(inSettings, true)}
          >
            Settings
          </a>
        </div>
      ) : null}
    </nav>
  );
}
