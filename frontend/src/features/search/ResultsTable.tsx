import { EmptyState } from "@/components/EmptyState";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { SeverityBadge } from "@/components/SeverityBadge";
import type { Cell, GeoInfo, QueryResult } from "@/lib/api";
import { EntityLink } from "@/components/EntityLink";
import { Truncate } from "@/components/Truncate";
import { When } from "@/components/When";
import { isIsoTime } from "@/features/ask/AskResults";
import { kindForColumn, type EntityKind } from "@/lib/entity";
import { cn } from "@/lib/cn";
import { geoShort } from "@/lib/geo";
import { intelLine } from "@/lib/intel";
import {
  columnLabel,
  columnTemplate,
  displayCell,
  formatCell,
  isNameColumn,
  sortRows,
  type SortDir,
} from "@/lib/search";
import { EventDetail } from "./EventDetail";
import { RawLines } from "./RawLines";
import { Select } from "@/components/forms/Select";

const PAGE_SIZES = [50, 100, 500] as const;
const SIZE_KEY = "results.pageSize";

/** The viewer's rows per page, kept in this browser. */
function storedSize(): number {
  try {
    const n = Number(window.localStorage.getItem(SIZE_KEY));
    return (PAGE_SIZES as readonly number[]).includes(n) ? n : PAGE_SIZES[0];
  } catch {
    return PAGE_SIZES[0];
  }
}

const PAGE_BUTTON =
  "h-7 rounded border border-border-strong px-2.5 text-text hover:bg-surface-head disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent";

interface PagerProps {
  page: number;
  pages: number;
  size: number;
  total: number;
  /** The result holds only the newest rows of what matched. */
  truncated: boolean;
  onPage: (page: number) => void;
  onSize: (size: number) => void;
}

/** Previous and Next beside the count, and the rows per page (owner, 2026-11-13). Drawn
 * above and below the rows, so the way to row 51 is never only under row 50. */
function Pager({ page, pages, size, total, truncated, onPage, onSize }: PagerProps) {
  return (
    <nav
      aria-label="Result pages"
      data-pager=""
      data-page={page + 1}
      data-pages={pages}
      className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3.5 py-2 text-sm text-text-secondary"
    >
      <button
        type="button"
        data-pager-previous=""
        disabled={page === 0}
        onClick={() => onPage(page - 1)}
        className={PAGE_BUTTON}
      >
        Previous
      </button>
      <button
        type="button"
        data-pager-next=""
        disabled={page >= pages - 1}
        onClick={() => onPage(page + 1)}
        className={PAGE_BUTTON}
      >
        Next
      </button>
      <span data-pager-range="" className="tabular-nums">
        {(page * size + 1).toLocaleString()} to{" "}
        {Math.min((page + 1) * size, total).toLocaleString()} of {total.toLocaleString()}
        {truncated ? " (the newest rows; narrow the range or filters to see all)" : ""}
      </span>
      <label className="flex items-center gap-1.5">
        Rows per page
        <Select
          aria-label="Rows per page"
          value={String(size)}
          onChange={(v) => onSize(Number(v))}
          options={PAGE_SIZES.map((n) => ({ value: String(n), label: String(n) }))}
          className="h-7"
        />
      </label>
    </nav>
  );
}
const HIDDEN_COLUMNS = new Set(["event_id"]);

interface ResultsTableProps {
  result: QueryResult;
  view: "parsed" | "raw";
  /** Column names the viewer chose to hide. */
  hidden?: string[];
  /** 30px rows instead of 36px (DESIGN.md 4). */
  compact?: boolean;
  /** Event ids chosen for Explain, and how to change them; absent when Explain is off. */
  selected?: Set<string>;
  onToggleSelect?: (eventId: string) => void;
  /** Location of public addresses, when the viewer shows it (ADR-0023 row 6). */
  geo?: Record<string, GeoInfo>;
  /** Event ids that just arrived (Live, ADR-0036): a short tint, once. */
  fresh?: Set<string>;
  /** Told when a row opens or closes (Live holds new rows while one is open). */
  onOpenChange?: (open: boolean) => void;
  /** Times in the viewer's zone with UTC on hover, as Ask shows them (on by default since
   * 2026-11-08: Logs and Microsoft 365 tables showed raw UTC). False keeps UTC stamps. */
  localTimes?: boolean;
  /** A view's own headers for the columns its server query names (Microsoft 365 views);
   * any other column keeps the shared label. */
  labels?: Readonly<Record<string, string>>;
  /** The view states the count beside its title: no "N rows" line under a single page. */
  counted?: boolean;
  /** An address's place in its tooltip instead of beside it, so a narrow table gives the
   * width to the names (the person page's Microsoft 365, owner 2026-11-16). */
  placeOnHover?: boolean;
  /** A library query's own words for no rows (D274), in place of the generic advice. */
  emptyDetail?: string;
}

export function ResultsTable({
  result,
  view,
  hidden = [],
  compact = false,
  selected,
  onToggleSelect,
  geo,
  fresh,
  onOpenChange,
  localTimes = true,
  labels,
  counted = false,
  placeOnHover = false,
  emptyDetail,
}: ResultsTableProps) {
  const geoOf = (v: unknown) => (geo && typeof v === "string" ? geo[v] : undefined);
  const intelOf = (v: unknown) =>
    result.intel && typeof v === "string" ? result.intel[v] : undefined;
  const idIndex = result.columns.indexOf("event_id");
  // The open row, by event id when the result has one, so rows added above it (Live)
  // neither move the detail to another row nor close it.
  const [open, setOpenKey] = useState<string | null>(null);
  const setOpen = (key: string | null) => {
    setOpenKey(key);
    onOpenChange?.(key !== null);
  };
  const keyOf = (row: Cell[], index: number) =>
    idIndex >= 0 && row[idIndex] != null ? `id:${String(row[idIndex])}` : `at:${index}`;
  const [wanted, setPage] = useState(0);
  const [size, setSizeState] = useState(storedSize);
  const setSize = (n: number) => {
    setSizeState(n);
    setPage(0);
    try {
      window.localStorage.setItem(SIZE_KEY, String(n));
    } catch {
      // Storage blocked: the choice lasts for this table only.
    }
  };
  const [sort, setSort] = useState<{ index: number; dir: SortDir } | null>(null);
  // The table is as wide as its box: Message takes what the other columns leave and
  // truncates (owner, 2026-11-13). Only when the other columns alone need more than the box
  // does it scroll sideways, inside the box; an open row's detail is pinned to the visible
  // width so the raw line and actions never sit off screen.
  const scroller = useRef<HTMLDivElement>(null);
  const [paneWidth, setPaneWidth] = useState<number | null>(null);
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const update = () => setPaneWidth(el.clientWidth);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const all = result.columns.map((c, i) => ({ c, i })).filter(({ c }) => !HIDDEN_COLUMNS.has(c));
  const chosen = all.filter(({ c }) => !hidden.includes(c));
  // Columns hidden for an earlier query never leave this one with nothing to show.
  const visible = chosen.length ? chosen : all;
  // Another result (another query, or a rerun that returned another number of rows) opens
  // on its first page. Not while Live adds rows to the one being read (`fresh`).
  const shown = `${result.executed_sql}|${result.rows.length}`;
  const [seen, setSeen] = useState(shown);
  if (shown !== seen) {
    setSeen(shown);
    if (!fresh) setPage(0);
  }
  const pages = Math.max(1, Math.ceil(result.rows.length / size));
  // And a shorter one never leaves the table on a page it does not have.
  const page = Math.min(wanted, pages - 1);
  const ordered = useMemo(
    () => (sort ? sortRows(result.rows, sort.index, sort.dir) : result.rows),
    [result.rows, sort],
  );
  const rows = ordered.slice(page * size, page * size + size);
  // Click cycles ascending, descending, then the order the query returned.
  const toggleSort = (index: number) => {
    setOpen(null);
    setPage(0);
    setSort((s) =>
      s?.index !== index ? { index, dir: "asc" } : s.dir === "asc" ? { index, dir: "desc" } : null,
    );
  };
  const template = columnTemplate(
    result.columns,
    rows,
    visible.map(({ i }) => i),
    48,
    (v) => {
      const g = placeOnHover ? undefined : geoOf(v);
      return (g ? geoShort(g).length + 2 : 0) + (intelOf(v) ? 2 : 0);
    },
  );

  if (result.rows.length === 0) {
    // An empty scope is not an empty result: say why (ADR-0004, no groups means no events).
    const noScope = result.sources.length === 0;
    return (
      <EmptyState
        kind={noScope ? "restricted" : "filtered"}
        title={noScope ? "No sources to search" : "No events match"}
        detail={
          noScope
            ? "None are shared with you yet. An administrator adds sources and shares them through source groups."
            : (emptyDetail ?? "Try a wider time range or remove a source filter.")
        }
      />
    );
  }

  // More rows than the smallest page: the pager, above and below.
  const paged = result.rows.length > PAGE_SIZES[0];
  const pager = (
    <Pager
      page={page}
      pages={pages}
      size={size}
      total={result.rows.length}
      truncated={result.truncated}
      onPage={(p) => {
        setOpen(null);
        setPage(p);
      }}
      onSize={(n) => {
        setOpen(null);
        setSize(n);
      }}
    />
  );
  return (
    <>
      {paged ? pager : null}
      {view === "raw" ? <RawLines result={result} rows={rows} /> : null}
      <div
        ref={scroller}
        data-scroll-x="results"
        className={cn("overflow-x-auto", view === "raw" && "hidden")}
        style={compact ? ({ "--row-h": "30px" } as CSSProperties) : undefined}
      >
        {/* A treegrid: rows expand to show the event (aria-expanded needs this role). */}
        <div
          role="treegrid"
          aria-label="Search results"
          data-total={result.rows.length}
          className="w-full min-w-min"
        >
          <div
            role="row"
            className="grid border-b border-border bg-surface-head px-3.5 py-2 font-mono text-sm font-semibold text-text-secondary"
            style={{ gridTemplateColumns: template }}
          >
            <span role="columnheader" aria-label="Expand" />
            {visible.map(({ c, i }) => (
              <span
                role="columnheader"
                key={c}
                aria-sort={
                  sort?.index === i ? (sort.dir === "asc" ? "ascending" : "descending") : "none"
                }
                className="truncate pr-4 font-sans"
              >
                <button
                  type="button"
                  onClick={() => toggleSort(i)}
                  title={`${c} · sort the rows shown`}
                  className="inline-flex max-w-full items-center gap-1 truncate hover:text-text"
                >
                  {labels?.[c] ?? columnLabel(c)}
                  {sort?.index === i ? (
                    sort.dir === "asc" ? (
                      <ArrowUp size={12} aria-hidden />
                    ) : (
                      <ArrowDown size={12} aria-hidden />
                    )
                  ) : null}
                </button>
              </span>
            ))}
          </div>
          {rows.map((row, idx) => {
            const index = page * size + idx;
            const key = keyOf(row, index);
            const isOpen = open === key;
            return (
              <Fragment key={key}>
                {/* A row, not a button, so values inside can be links (product pass step 2). */}
                <div
                  role="row"
                  tabIndex={0}
                  aria-level={1}
                  aria-expanded={isOpen}
                  onClick={() => setOpen(isOpen ? null : key)}
                  onKeyDown={(e) => {
                    if (e.target !== e.currentTarget) return;
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setOpen(isOpen ? null : key);
                    }
                  }}
                  className={cn(
                    // Mono on the grid so the ch-based column widths match the values.
                    "grid min-h-row w-full cursor-pointer items-center border-b border-border px-3.5 text-left font-mono text-sm text-text hover:bg-row-selected focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring",
                    isOpen && "bg-row-selected",
                    fresh && "transition-colors duration-1000 motion-reduce:transition-none",
                    fresh && idIndex >= 0 && fresh.has(String(row[idIndex])) && "bg-accent-subtle",
                  )}
                  style={{ gridTemplateColumns: template }}
                >
                  <span aria-hidden className="text-text-muted">
                    {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </span>
                  {visible.map(({ c, i }) => (
                    <span
                      role="gridcell"
                      key={c}
                      className={cn(
                        "truncate pr-4",
                        c === "message" && "font-sans text-base",
                        row[i] === null && "text-text-muted",
                      )}
                    >
                      {c === "severity_id" ? (
                        <SeverityBadge value={row[i]} />
                      ) : (
                        <>
                          {intelOf(row[i]) ? (
                            <span
                              role="img"
                              aria-label="Listed in threat intel"
                              title={(intelOf(row[i]) ?? []).map(intelLine).join("\n")}
                              className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-danger align-middle"
                            />
                          ) : null}
                          {localTimes && isIsoTime(row[i] ?? null) ? (
                            <When iso={row[i] as string} seconds />
                          ) : kindForColumn(c) ? (
                            <EntityLink
                              kind={kindForColumn(c) as EntityKind}
                              value={row[i]}
                              label={displayCell(row[i] ?? null)}
                              // The place on hover, where the link's own tooltip shows it.
                              hint={
                                placeOnHover && geoOf(row[i])
                                  ? geoShort(geoOf(row[i]) as GeoInfo)
                                  : undefined
                              }
                            />
                          ) : isNameColumn(c) && typeof row[i] === "string" ? (
                            // Cut in the middle, so two long names stay told apart.
                            <Truncate kind="name" value={row[i] as string} />
                          ) : (
                            <span title={formatCell(row[i] ?? null)}>
                              {displayCell(row[i] ?? null)}
                            </span>
                          )}
                          {geoOf(row[i]) && !placeOnHover ? (
                            <span className="ml-2 text-text-muted">
                              {geoShort(geoOf(row[i]) as GeoInfo)}
                            </span>
                          ) : null}
                        </>
                      )}
                    </span>
                  ))}
                </div>
                {isOpen ? (
                  <div
                    role="row"
                    aria-level={2}
                    className="sticky left-0"
                    style={paneWidth ? { width: paneWidth } : undefined}
                  >
                    <div role="gridcell">
                      <EventDetail
                        columns={result.columns}
                        row={row}
                        geo={geo}
                        intel={result.intel}
                        selection={
                          selected && onToggleSelect && idIndex >= 0
                            ? {
                                selected: selected.has(String(row[idIndex])),
                                toggle: () => onToggleSelect(String(row[idIndex])),
                              }
                            : undefined
                        }
                      />
                    </div>
                  </div>
                ) : null}
              </Fragment>
            );
          })}
        </div>
      </div>
      {paged ? (
        pager
      ) : counted ? null : (
        <p className="px-3.5 py-2 text-sm text-text-secondary">
          {result.rows.length.toLocaleString()} {result.rows.length === 1 ? "row" : "rows"}
          {result.truncated ? " (the newest rows; narrow the range or filters to see all)" : ""}
        </p>
      )}
      {geo && Object.keys(geo).length ? (
        // Attribution the DB-IP Lite license (CC BY 4.0) asks for: once, and quiet (F52).
        <p className="px-3.5 pb-2 text-xs text-text-muted">
          Locations:{" "}
          <a
            href="https://db-ip.com"
            target="_blank"
            rel="noreferrer"
            className="text-text-muted underline-offset-2 hover:underline"
          >
            IP Geolocation by DB-IP
          </a>
        </p>
      ) : null}
    </>
  );
}
