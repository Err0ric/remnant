import { ChevronDown, MoreHorizontal } from "lucide-react";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { cn } from "@/lib/cn";
import { areaOf, visibleTabs, type AreaTab } from "@/lib/nav";
import {
  fragmentValues,
  navigate,
  navigateTab,
  pathFor,
  usePage,
  type PageId,
  useSection,
  useTab,
} from "@/lib/route";
import { useViewer } from "@/lib/viewer";

/** A button in the page header. */
export interface HeaderAction {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  /** Hover hint; the accessible name is the label. */
  title?: string;
  /** For a toggle such as "Edit layout". */
  pressed?: boolean;
}

interface PageHeaderProps {
  /** The page's name, never its group's. Until the rail lists pages only (build row 4), a
   * page inside an old tabbed area is still titled by that area. */
  title: string;
  /** Shown beside the title ("12 open"). */
  count?: ReactNode;
  /** Outlined buttons. The first two are shown; any more go into the overflow menu. */
  secondary?: HeaderAction[];
  /** Overflow menu items, behind "More". */
  menu?: HeaderAction[];
  /** The page's one filled button, last on the right. One object, so never two. */
  primary?: HeaderAction;
  /** A Record page (DESIGN.md 6.0): the page it was reached from, above the title, which
   * is then the record's own name at `text-xl`. */
  breadcrumb?: { label: string; page: PageId };
  /** The title is a logged value (an address, a host, a user name): mono. */
  mono?: boolean;
  /** Counts or flags beside tab labels, by tab label ("Sessions": 214). */
  tabExtras?: Record<string, ReactNode>;
  /** Problems on a tab, by tab label: an outlined warn tag, drawn only above zero (D255). */
  tabProblems?: Record<string, number>;
}

function key(t: AreaTab): string {
  return `${t.page}:${t.tab ?? ""}`;
}

const SECONDARY =
  "h-8 whitespace-nowrap rounded border border-border-strong px-3 text-text hover:bg-surface-head disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent";

interface OverflowProps {
  items: HeaderAction[];
  /** A named menu ("Views") shows its name on the button; without one it is "More". */
  label?: string;
}

function Overflow({ items, label }: OverflowProps) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  const menuItems = () => [
    ...(box.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? []),
  ];
  // Esc and a choice give focus back to the button; a click or Tab elsewhere just closes.
  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  };
  useEffect(() => {
    if (!open) return;
    menuItems()[0]?.focus();
    const away = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const onKey = (e: ReactKeyboardEvent) => {
    if (!open) return;
    if (e.key === "Escape") {
      e.preventDefault();
      close(true);
      return;
    }
    const all = menuItems();
    const at = all.indexOf(document.activeElement as HTMLButtonElement);
    const to =
      e.key === "ArrowDown"
        ? (at + 1) % all.length
        : e.key === "ArrowUp"
          ? (at - 1 + all.length) % all.length
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? all.length - 1
              : -1;
    if (to < 0) return;
    e.preventDefault();
    all[to]?.focus();
  };
  return (
    <div
      ref={box}
      className="relative"
      onKeyDown={onKey}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <button
        ref={trigger}
        type="button"
        aria-label={label ?? "More actions"}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          SECONDARY,
          label ? "flex items-center gap-1.5" : "flex w-8 items-center justify-center px-0",
        )}
      >
        {label ? (
          <>
            {label}
            <ChevronDown size={14} aria-hidden />
          </>
        ) : (
          <MoreHorizontal size={16} aria-hidden />
        )}
      </button>
      {open ? (
        <div
          id={menuId}
          role="menu"
          className="absolute right-0 top-full z-40 mt-1 min-w-40 rounded-card border border-border bg-surface p-1 shadow-lg"
        >
          {items.map((it) => (
            <button
              key={it.label}
              type="button"
              role="menuitem"
              disabled={it.disabled}
              title={it.title}
              onClick={() => {
                close(true);
                it.onClick();
              }}
              className="block w-full whitespace-nowrap rounded px-2.5 py-1.5 text-left hover:bg-surface-head disabled:opacity-40"
            >
              {it.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** The page header (DESIGN.md 5 and 6.0): the title and an optional count; on the right up
 * to two secondary buttons, an overflow menu, and at most one filled primary button, last;
 * then the page's tabs. In the document the order is title, tabs, actions, which is also
 * the keyboard order; the actions sit on the title's row on screen. */
export function PageHeader({
  title,
  count,
  secondary = [],
  menu = [],
  primary,
  breadcrumb,
  mono = false,
  tabExtras,
  tabProblems,
}: PageHeaderProps) {
  const page = usePage();
  const tab = useTab();
  // The page's time choice lives in the fragment (ADR-0052 section 3.7: one time control
  // per page), so a tab of the same page keeps it.
  const frag = fragmentValues(useSection());
  const time = new URLSearchParams();
  for (const k of ["time", "from", "to"]) {
    const v = frag.get(k);
    if (v) time.set(k, v);
  }
  const keeps = (t: { page: string; tab?: string }) =>
    t.page === page && t.tab !== undefined && time.toString() !== "";
  const { isAdmin, canAsk = true, canRunSql = true } = useViewer();
  const place = areaOf(page, tab);
  const tabs = place ? visibleTabs(place.area, isAdmin, canAsk, canRunSql) : [];
  // The page's views (Logs: the Microsoft 365 lists), behind one "Views" menu on every tab
  // of the page. They are server-built lists, so they do not depend on SQL access. The
  // first item goes back to the page's own first tab.
  const viewTabs = place ? place.area.tabs.filter((t) => t.view) : [];
  const views: HeaderAction[] = viewTabs.length
    ? [
        ...(tabs[0]
          ? [
              {
                label: tabs[0].label,
                onClick: () => navigate(tabs[0]!.page, tabs[0]!.tab),
                // Already there: the open place is the disabled item, as for a view.
                disabled: key(tabs[0]) === key(place!.tab),
              },
            ]
          : []),
        ...viewTabs.map((t) => ({
          label: t.label,
          onClick: () => navigate(t.page, t.tab),
          disabled: key(t) === key(place!.tab),
        })),
      ]
    : [];
  const withTabs = tabs.length > 1;
  const shown = secondary.slice(0, 2);
  const more = [...secondary.slice(2), ...menu];
  const hasActions =
    shown.length > 0 || more.length > 0 || views.length > 0 || primary !== undefined;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] border-b border-border bg-surface px-5">
      {breadcrumb ? (
        <nav aria-label="Breadcrumb" className="col-span-2 row-start-1 pt-2 text-sm">
          <a
            href={pathFor(breadcrumb.page)}
            onClick={(e: ReactMouseEvent) => {
              if (e.metaKey || e.ctrlKey || e.shiftKey) return;
              e.preventDefault();
              navigate(breadcrumb.page);
            }}
            className="text-accent-text no-underline hover:underline"
          >
            {breadcrumb.label}
          </a>
          <span aria-hidden className="px-1.5 text-text-muted">
            /
          </span>
        </nav>
      ) : null}
      <div
        className={cn(
          "col-start-1 flex min-h-11 min-w-0 items-center gap-2",
          breadcrumb ? "row-start-2" : "row-start-1",
        )}
      >
        {breadcrumb ? (
          <h1 className={cn("min-w-0 text-xl [overflow-wrap:anywhere]", mono && "font-mono")}>
            {title}
          </h1>
        ) : (
          <h1 className="shrink-0 whitespace-nowrap text-lg">
            {withTabs && place ? place.area.label : title}
          </h1>
        )}
        {count !== undefined && count !== null ? (
          <span data-header-count="" className="min-w-0 truncate text-text-secondary">
            {count}
          </span>
        ) : null}
      </div>
      {withTabs && place && !breadcrumb ? (
        <nav
          aria-label={`${place.area.label} tabs`}
          className="col-span-2 row-start-2 -mb-px flex h-9 items-end gap-5 overflow-x-auto"
        >
          {tabs.map((t) => {
            const on = key(t) === key(place.tab);
            return (
              <a
                key={key(t)}
                href={pathFor(t.page, t.tab) + (keeps(t) ? `#${time.toString()}` : "")}
                aria-current={on ? "page" : undefined}
                onClick={(e: ReactMouseEvent) => {
                  if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                  e.preventDefault();
                  if (keeps(t) && t.tab) navigateTab(t.page, t.tab, time.toString());
                  else navigate(t.page, t.tab);
                }}
                className={cn(
                  "whitespace-nowrap border-b-2 pb-2 pt-1.5 no-underline",
                  on
                    ? "border-accent-text font-semibold text-text"
                    : "border-transparent font-medium text-text-secondary hover:text-text",
                )}
              >
                {t.label}
                {tabExtras?.[t.label] !== undefined ? (
                  <span className="ml-1 font-normal text-text-muted">{tabExtras[t.label]}</span>
                ) : null}
                {(tabProblems?.[t.label] ?? 0) > 0 ? (
                  <span
                    data-problems=""
                    title={`${tabProblems?.[t.label]} need attention`}
                    className="ml-1 rounded-badge border border-warn px-1 text-xs font-semibold tabular-nums text-warn"
                  >
                    {tabProblems?.[t.label]}
                  </span>
                ) : null}
              </a>
            );
          })}
        </nav>
      ) : null}
      {hasActions ? (
        <div
          data-header-actions=""
          // On a phone the buttons take their own row under the title and tabs.
          className={cn(
            "col-start-2 flex flex-wrap items-center justify-end gap-2 py-1.5 pl-3 max-sm:col-span-2 max-sm:col-start-1 max-sm:row-start-3 max-sm:justify-start max-sm:pl-0",
            breadcrumb ? "row-start-2" : "row-start-1",
          )}
        >
          {shown.map((a) => (
            <button
              key={a.label}
              type="button"
              onClick={a.onClick}
              disabled={a.disabled}
              title={a.title}
              aria-pressed={a.pressed}
              className={cn(SECONDARY, a.pressed && "border-accent-text bg-accent-subtle")}
            >
              {a.label}
            </button>
          ))}
          {views.length ? <Overflow label="Views" items={views} /> : null}
          {more.length ? <Overflow items={more} /> : null}
          {primary ? (
            <button
              type="button"
              data-primary=""
              onClick={primary.onClick}
              disabled={primary.disabled}
              title={primary.title}
              className="h-8 whitespace-nowrap rounded bg-accent px-3 font-medium text-on-accent hover:opacity-90 disabled:cursor-default disabled:opacity-40"
            >
              {primary.label}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
