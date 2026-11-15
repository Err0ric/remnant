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
  /** This window minus the one before; left out when the window before is unknown. */
  change?: number | null;
  /** One context line under the value. */
  context?: ReactNode;
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
          <Skeleton
            label={label}
            block="my-1 h-7 w-1/3 rounded bg-surface-head"
            className="rounded-none border-0 bg-transparent"
          />
          <Skeleton
            label={label}
            block="my-1 h-3 w-2/3 rounded bg-surface-head"
            className="rounded-none border-0 bg-transparent"
          />
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
            {change !== null && change !== undefined ? (
              <ChangePill
                change={change}
                spoken={`${change === 0 ? "same as" : `${change > 0 ? "up" : "down"} ${Math.abs(change).toLocaleString()} from`} the window before`}
              />
            ) : null}
          </span>
          {context ? <span className="line-clamp-2 text-sm text-text-muted">{context}</span> : null}
        </>
      )}
    </div>
  );
}
