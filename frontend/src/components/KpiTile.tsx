import type { ReactNode } from "react";
import { About } from "@/components/About";
import { ChangePill } from "@/components/ChangePill";
import { PanelTitle } from "@/components/PanelTitle";
import { Skeleton } from "@/components/Skeleton";
import { cn } from "@/lib/cn";
import { navigate, pathFor, type PageId } from "@/lib/route";

interface KpiTileProps {
  label: string;
  /** The headline; a string for "7 of 8". */
  value: ReactNode;
  /** Zero reads muted; a problem reads in the warn color with its words beside it. */
  tone?: "text" | "muted" | "warn";
  /** This window minus the one before. Null: the number is compared, but its sources have
   * no data for the window before, so the tile says "No earlier data" in place of a change,
   * never a change from zero (fix list item 9). Left out: the number is never compared. */
  change?: number | null;
  /** One context line under the value. */
  context?: ReactNode;
  /** Lines the context may take before it is cut (default 2). */
  contextLines?: 2 | 4;
  /** Where the value leads; without it the value is plain text. */
  page?: PageId;
  tab?: string;
  /** The place's name, for a screen reader: "Open Health". */
  opens?: string;
  /** How the number is counted, behind the (i) (owner, 2026-11-02). */
  about?: string;
  /** Hover text for the value (a UTC time). */
  title?: string;
  /** The data is not there yet: the value and context line are bars of their final height,
   * never a zero or an all-clear (D255). */
  loading?: boolean;
  /** While loading, a bar for the context line (default), or none for a tile that has none
   * loaded, so the tile is as tall loading as loaded. */
  contextLine?: boolean;
  /** The data could not be read: a muted "Could not load" with Retry, never a number. */
  failed?: () => void;
}

/** One KPI tile (DESIGN.md 6.3, D255): the label as a `PanelTitle` with its (i), the value in
 * `text-kpi` that opens the place to act on it, an optional change pill, and one context
 * line. Tiles sit in one strip with hairline dividers: a grid with `gap-px` on `bg-border`. */
export function KpiTile({
  label,
  value,
  tone = "text",
  change,
  context,
  page,
  tab,
  opens,
  about,
  title,
  loading = false,
  contextLine = true,
  contextLines = 2,
  failed,
}: KpiTileProps) {
  const cls = cn(
    "text-kpi tabular-nums no-underline min-[1500px]:text-kpi-lg",
    tone === "muted" ? "text-text-muted" : tone === "warn" ? "text-warn" : "text-text",
  );
  return (
    <div data-kpi={label} className="flex min-w-0 flex-col gap-0.5 bg-surface px-3 py-2.5">
      <span className="flex min-w-0 items-start gap-1.5">
        <PanelTitle as="span" className="line-clamp-2 min-w-0" title={label}>
          {label}
        </PanelTitle>
        {about ? <About text={about} /> : null}
      </span>
      {failed ? (
        <span role="alert" className="flex flex-wrap items-center gap-x-2 text-sm text-text-muted">
          Could not load
          <button
            type="button"
            onClick={failed}
            aria-label={`Retry ${label}`}
            className="text-accent-text hover:underline"
          >
            Retry
          </button>
        </span>
      ) : loading ? (
        <>
          {/* The value's line height at each width and density, and one `text-sm` line:
              the tile is as tall loading as loaded with its context line (item 27). */}
          <Skeleton
            label={label}
            block="my-1 h-[calc(var(--lh-kpi)-8px)] w-1/3 rounded bg-border-strong min-[1500px]:h-[calc(var(--lh-kpi-lg)-8px)]"
            className="rounded-none border-0 bg-transparent"
          />
          {contextLine ? (
            <Skeleton
              label={label}
              block="my-[3px] h-3 w-2/3 rounded bg-border-strong"
              className="rounded-none border-0 bg-transparent"
            />
          ) : null}
        </>
      ) : (
        <>
          <span className="flex flex-wrap items-center gap-x-2">
            {page ? (
              <a
                href={`${pathFor(page)}${tab ? `#${tab}` : ""}`}
                title={title}
                onClick={(e) => {
                  if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                  e.preventDefault();
                  navigate(page, tab);
                }}
                aria-label={`${label}: ${typeof value === "string" || typeof value === "number" ? value : ""}. Open ${opens ?? ""}`}
                className={cn(cls, "hover:underline")}
              >
                {value}
              </a>
            ) : (
              <span title={title} className={cls}>
                {value}
              </span>
            )}
            {change === null ? (
              <span data-change="none" className="text-sm text-text-muted">
                No earlier data
              </span>
            ) : change !== undefined ? (
              <ChangePill
                change={change}
                spoken={`${change === 0 ? "same as" : `${change > 0 ? "up" : "down"} ${Math.abs(change).toLocaleString()} from`} the window before`}
              />
            ) : null}
          </span>
          {context ? (
            <span
              className={cn(
                "text-sm text-text-muted",
                contextLines === 4 ? "line-clamp-4" : "line-clamp-2",
              )}
            >
              {context}
            </span>
          ) : null}
        </>
      )}
    </div>
  );
}
