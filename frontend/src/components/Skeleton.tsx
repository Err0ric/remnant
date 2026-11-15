import { cn } from "@/lib/cn";

interface SkeletonProps {
  /** What is loading, for a screen reader: "alerts". */
  label: string;
  /** Rows to hold the place of, so the page does not jump when the data arrives. */
  rows?: number;
  /** A block of one height instead of rows (a chart, a card): a Tailwind height class. */
  block?: string;
  /** A column header row above the rows, as the loaded table has. */
  header?: boolean;
  /** Rows two lines high, for a table whose rows carry a second line. */
  tall?: boolean;
  className?: string;
}

/** Loading (DESIGN.md 6.0): rows in the final layout, at the page's row height, so nothing
 * shifts when the data arrives. Never a spinner; those are only inside buttons. On a
 * refresh the old data stays on screen, so this shows on a first load only. */
export function Skeleton({
  label,
  rows = 3,
  block,
  header = false,
  tall = false,
  className,
}: SkeletonProps) {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label={`Loading ${label}`}
      data-skeleton=""
      className={cn("overflow-hidden rounded-card border border-border bg-surface", className)}
    >
      {block ? (
        <div className={cn("animate-pulse bg-surface-head/60", block)} />
      ) : (
        <>
          {header ? (
            <div
              data-skeleton-header=""
              className="flex h-12 items-center gap-3 border-b border-border px-3"
            >
              <span className="h-2 w-1/6 animate-pulse rounded bg-surface-head" />
              <span className="h-2 w-1/6 animate-pulse rounded bg-surface-head" />
              <span className="h-2 w-1/6 animate-pulse rounded bg-surface-head" />
            </div>
          ) : null}
          {Array.from({ length: rows }, (_, i) => (
            <div
              key={i}
              data-skeleton-row={tall ? "tall" : ""}
              className={cn(
                "flex items-center gap-3 border-b border-border px-3 last:border-0",
                tall ? "h-14" : "h-[var(--row-h)]",
              )}
            >
              {tall ? (
                <span className="flex w-1/4 flex-col gap-2">
                  <span className="h-2.5 w-full animate-pulse rounded bg-surface-head" />
                  <span className="h-2 w-2/3 animate-pulse rounded bg-surface-head" />
                </span>
              ) : (
                <span className="h-2.5 w-1/4 animate-pulse rounded bg-surface-head" />
              )}
              <span className="h-2.5 w-2/5 animate-pulse rounded bg-surface-head" />
            </div>
          ))}
        </>
      )}
    </div>
  );
}
