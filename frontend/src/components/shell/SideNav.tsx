import type { MouseEvent } from "react";
import { cn } from "@/lib/cn";
import {
  NAV_GROUPS as GROUPS,
  SETTINGS_IDS,
  visibleSections,
  visibleSettings,
  type NavItem,
} from "@/lib/nav";
import { navigate, pathFor, useSection, type PageId } from "@/lib/route";

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

function Item({ item, active, isAdmin }: { item: NavItem; active: string; isAdmin: boolean }) {
  const section = useSection();
  const sections = item.id === active ? visibleSections(item, isAdmin) : [];
  const current = sections.some((x) => x.id === section) ? section : sections[0]?.id;
  return (
    <>
      {link(item, active)}
      {sections.length > 0 && item.page ? (
        <ul aria-label={`${item.label} sections`} className="mb-1 ml-3 border-l border-border pl-2">
          {sections.map((x) => (
            <li key={x.id}>
              <a
                href={`${pathFor(item.page as PageId)}#${x.id}`}
                onClick={(e) => {
                  if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                  e.preventDefault();
                  navigate(item.page as PageId, x.id);
                }}
                aria-current={x.id === current ? "location" : undefined}
                className={cn(
                  "block rounded px-2.5 py-1 text-sm no-underline",
                  x.id === current
                    ? "font-semibold text-accent-text"
                    : "text-text-secondary hover:bg-surface-head hover:text-text",
                )}
              >
                {x.label}
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

function link(item: NavItem, active: string) {
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
  // Settings opens on Sources, the page used most; the checklist is first in its list.
  const items = settings.flatMap((g) => g.items);
  const first = (items.find((i) => i.id === "sources") ?? items[0])?.page;
  const inSettings = SETTINGS_IDS.has(active);
  return (
    <nav
      id="primary-nav"
      aria-label="Primary"
      className={cn(
        // From md up the rail stays in view under the top bar, with Settings pinned to its foot.
        "w-full shrink-0 border-b border-border bg-nav px-2 py-3 md:sticky md:top-12 md:flex md:h-[calc(100dvh-3rem)] md:w-55 md:flex-col md:self-start md:border-b-0 md:border-r",
        open ? "block" : "hidden",
      )}
    >
      {/* The groups scroll on short screens; Settings below stays in view. */}
      <div className="md:min-h-0 md:flex-1 md:overflow-y-auto">
        {GROUPS.map((group) => (
          <div key={group.label} className="mb-3">
            <div className="px-2.5 py-1 text-xs text-text-muted">{group.label}</div>
            {group.items
              .filter((item) => (isAdmin || !item.adminOnly) && (canAudit || !item.auditOnly))
              .map((item) => (
                <Item key={item.id} item={item} active={active} isAdmin={isAdmin} />
              ))}
          </div>
        ))}
      </div>
      {first ? (
        <div className="shrink-0 border-t border-border pt-3">
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
