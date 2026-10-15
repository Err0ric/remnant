import { ArrowDown, ArrowUp, ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { SeverityBadge } from "@/components/SeverityBadge";
import type { QueryResult } from "@/lib/api";
import { cn } from "@/lib/cn";
import {
  columnLabel,
  columnTemplate,
  displayCell,
  formatCell,
  sortRows,
  type SortDir,
} from "@/lib/search";
import { EventDetail } from "./EventDetail";
import { RawLines } from "./RawLines";

const PAGE = 50;
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
}

export function ResultsTable({
  result,
  view,
  hidden = [],
  compact = false,
  selected,
  onToggleSelect,
}: ResultsTableProps) {
  const idIndex = result.columns.indexOf("event_id");
  const [open, setOpen] = useState<number | null>(null);
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<{ index: number; dir: SortDir } | null>(null);
  // The table is as wide as its widest value and scrolls sideways; an open row's detail
  // is pinned to the visible width so the raw line and actions never sit off screen.
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
  const pages = Math.max(1, Math.ceil(result.rows.length / PAGE));
  const ordered = useMemo(
    () => (sort ? sortRows(result.rows, sort.index, sort.dir) : result.rows),
    [result.rows, sort],
  );
  const rows = ordered.slice(page * PAGE, page * PAGE + PAGE);
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
  );

  if (result.rows.length === 0) {
    // An empty scope is not an empty result: say why (ADR-0004, no groups means no events).
    const noScope = result.sources.length === 0;
    return (
      <div className="px-4 py-10 text-center">
        <div className="text-md">{noScope ? "No sources to search" : "No events match"}</div>
        <div className="mt-1 text-text-secondary">
          {noScope
            ? "None are shared with you yet. An administrator adds sources and shares them through source groups."
            : "Try a wider time range or remove a source filter."}
        </div>
      </div>
    );
  }

  return (
    <>
      {view === "raw" ? <RawLines result={result} rows={rows} /> : null}
      <div
        ref={scroller}
        className={cn("overflow-x-auto", view === "raw" && "hidden")}
        style={compact ? ({ "--row-h": "30px" } as CSSProperties) : undefined}
      >
        {/* A treegrid: rows expand to show the event (aria-expanded needs this role). */}
        <div role="treegrid" aria-label="Search results" className="w-max min-w-full">
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
                  {columnLabel(c)}
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
            const index = page * PAGE + idx;
            const isOpen = open === index;
            return (
              <Fragment key={index}>
                <button
                  type="button"
                  role="row"
                  aria-level={1}
                  aria-expanded={isOpen}
                  onClick={() => setOpen(isOpen ? null : index)}
                  className={cn(
                    // Mono on the grid so the ch-based column widths match the values.
                    "grid min-h-row w-full items-center border-b border-border px-3.5 text-left font-mono text-sm text-text hover:bg-row-selected",
                    isOpen && "bg-row-selected",
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
                        <span title={formatCell(row[i] ?? null)}>
                          {displayCell(row[i] ?? null)}
                        </span>
                      )}
                    </span>
                  ))}
                </button>
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
      <div className="flex items-center gap-3 px-3.5 py-2 text-sm text-text-secondary">
        <span>
          {page * PAGE + 1} to {Math.min((page + 1) * PAGE, result.rows.length)} of{" "}
          {result.rows.length}
          {result.truncated ? " (limit reached)" : ""}
        </span>
        <span className="ml-auto flex gap-3">
          <button
            type="button"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
            className="text-accent-text disabled:opacity-40"
          >
            Previous
          </button>
          <button
            type="button"
            disabled={page >= pages - 1}
            onClick={() => setPage(page + 1)}
            className="text-accent-text disabled:opacity-40"
          >
            Next
          </button>
        </span>
      </div>
    </>
  );
}
