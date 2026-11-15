import type { ReactNode } from "react";
import { About } from "@/components/About";
import { PanelTitle } from "@/components/PanelTitle";
import { SectionTitle } from "@/components/SectionTitle";
import { cn } from "@/lib/cn";

interface CardProps {
  title: string;
  /** The region's name when it differs from the title ("Agent sessions" for "Sessions"). */
  label?: string;
  /** A page section (the `SectionTitle` pill, an h2) or a panel inside one (`PanelTitle`). */
  level?: "section" | "panel";
  /** How the card is counted, behind an (i) beside the title. */
  about?: string;
  /** One muted line beside the title: where the numbers come from, what they compare. */
  note?: ReactNode;
  /** A small status tag beside the title ("2 changed"): part of the note area, never an action. */
  badge?: ReactNode;
  /** One action at the top right, a `CardAction` ("View all", "Open AI usage"). */
  action?: ReactNode;
  className?: string;
  children?: ReactNode;
}

/** The one card anatomy (DESIGN.md 7, D254): a header row of one height and one padding
 * with no fill, holding the title, an optional (i), an optional muted note, and one action
 * last on the right; then the body. Cards side by side in a grid stretch to the tallest. */
export function Card({
  title,
  label,
  level = "section",
  about,
  note,
  badge,
  action,
  className,
  children,
}: CardProps) {
  return (
    <section
      aria-label={label ?? title}
      data-card={level}
      className={cn(
        "flex min-w-0 flex-col rounded-card border border-border bg-surface",
        className,
      )}
    >
      <div
        data-card-header=""
        className="flex h-10 min-w-0 shrink-0 items-center gap-x-2 border-b border-border px-3 py-2"
      >
        {level === "section" ? (
          <SectionTitle className="block min-w-0 truncate">{title}</SectionTitle>
        ) : (
          <PanelTitle className="min-w-0 truncate" title={title}>
            {title}
          </PanelTitle>
        )}
        {about ? <About text={about} /> : null}
        {note ? (
          <span
            data-card-note=""
            title={typeof note === "string" ? note : undefined}
            // The note gives way before the title does.
            className="ml-1 min-w-0 shrink-[100] truncate text-sm text-text-muted"
          >
            {note}
          </span>
        ) : null}
        {badge ? <span className="shrink-0">{badge}</span> : null}
        {action ? <div className="ml-auto flex shrink-0 items-center pl-2">{action}</div> : null}
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </section>
  );
}
