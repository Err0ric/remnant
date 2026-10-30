import type { MouseEvent, ReactNode } from "react";
import { cn } from "@/lib/cn";
import { areaOf, visibleTabs, type AreaTab } from "@/lib/nav";
import { navigate, pathFor, usePage, useTab } from "@/lib/route";
import { useViewer } from "@/lib/viewer";

interface PageHeaderProps {
  /** Kept for pages that still pass it; the area and its tabs say where you are (ADR-0038
   * row 8), so crumbs are not shown. */
  crumbs?: string[];
  title: string;
  commands?: ReactNode;
  meta?: ReactNode;
  /** Counts or flags beside tab labels, by tab label ("Sessions": 214). */
  tabExtras?: Record<string, ReactNode>;
}

function key(t: AreaTab): string {
  return `${t.page}:${t.tab ?? ""}`;
}

/** Title, the area's tabs (ADR-0038 rows 2 and 3), then the page's commands. A page in an
 * area with tabs is titled by its area; the open tab says which part of it. */
export function PageHeader({ title, commands, meta, tabExtras }: PageHeaderProps) {
  const page = usePage();
  const tab = useTab();
  const { isAdmin } = useViewer();
  const place = areaOf(page, tab);
  const tabs = place ? visibleTabs(place.area, isAdmin) : [];
  const withTabs = tabs.length > 1;
  return (
    <div className="border-b border-border bg-surface px-5 pt-3">
      <h1 className="text-lg">{withTabs && place ? place.area.label : title}</h1>
      {withTabs && place ? (
        <nav
          aria-label={`${place.area.label} tabs`}
          className="-mb-px mt-1 flex gap-5 overflow-x-auto"
        >
          {tabs.map((t) => {
            const on = key(t) === key(place.tab);
            return (
              <a
                key={key(t)}
                href={pathFor(t.page, t.tab)}
                aria-current={on ? "page" : undefined}
                onClick={(e: MouseEvent) => {
                  if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                  e.preventDefault();
                  navigate(t.page, t.tab);
                }}
                className={cn(
                  "whitespace-nowrap border-b-2 pb-2 pt-1.5 font-semibold no-underline",
                  on
                    ? "border-accent text-text"
                    : "border-transparent text-text-secondary hover:text-text",
                )}
              >
                {t.label}
                {tabExtras?.[t.label] !== undefined ? (
                  <span className="ml-1 font-normal text-text-muted">{tabExtras[t.label]}</span>
                ) : null}
              </a>
            );
          })}
        </nav>
      ) : null}
      {commands || meta ? (
        <div
          className={cn(
            "flex flex-wrap items-center gap-1 py-1",
            withTabs && "-mx-5 border-t border-border px-5",
          )}
        >
          {commands}
          {meta ? <span className="ml-auto text-sm text-text-secondary">{meta}</span> : null}
        </div>
      ) : (
        <div className={withTabs ? "" : "pb-2"} />
      )}
    </div>
  );
}

interface CommandProps {
  label: string;
  onClick?: () => void;
  primary?: boolean;
  disabled?: boolean;
  title?: string;
}

export function Command({ label, onClick, primary, disabled, title }: CommandProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`h-8 rounded px-3 hover:bg-surface-head disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent ${
        primary ? "font-semibold text-accent-text" : "text-text"
      }`}
    >
      {label}
    </button>
  );
}
