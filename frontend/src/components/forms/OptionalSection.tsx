import type { ReactNode } from "react";

interface OptionalSectionProps {
  /** What the section holds, e.g. "Parsing and retention". */
  title: string;
  /** The values in effect if nothing here is changed, in one line. */
  summary: string;
  children: ReactNode;
  defaultOpen?: boolean;
  /** Grid placement in the parent form; spans two columns by default. */
  span?: string;
}

/** Settings that already have a working default, kept apart from the required ones: a
 * dashed, labeled block, closed until opened, that says what applies if left alone. */
export function OptionalSection({
  title,
  summary,
  children,
  defaultOpen = false,
  span = "md:col-span-2",
}: OptionalSectionProps) {
  return (
    <details
      open={defaultOpen}
      className={`group rounded-card border border-dashed border-border-strong ${span}`}
    >
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2 text-sm">
        <span
          aria-hidden="true"
          className="inline-block w-3 text-text-muted transition-transform group-open:rotate-90"
        >
          ›
        </span>
        <span className="rounded-badge bg-surface-head px-1.5 py-px text-xs font-semibold uppercase tracking-wide text-text-secondary">
          Optional
        </span>
        <span className="font-semibold">{title}</span>
        <span className="min-w-0 text-text-muted">{summary}</span>
      </summary>
      <div className="grid gap-4 border-t border-dashed border-border-strong p-3 md:grid-cols-2">
        {children}
      </div>
    </details>
  );
}
