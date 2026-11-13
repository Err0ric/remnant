import type { ReactNode } from "react";

/** The five kinds of empty (DESIGN.md 6.0). */
export type EmptyKind =
  /** The page needs something the install lacks: "Needs a Microsoft 365 source". */
  | "not-set-up"
  /** The filters hide every row: the action is Reset filters. */
  | "filtered"
  /** Nothing to do, and that is good news: said in normal text, with no action. */
  | "good-zero"
  /** The page's default filter has no rows (the Inventory with nothing to review). */
  | "default-empty"
  /** Rows exist that this person may not read: never shown as zero. */
  | "restricted";

interface EmptyStateProps {
  kind: EmptyKind;
  /** The first line: what is true ("No alerts match these filters."). */
  title: ReactNode;
  /** An optional second line. Two lines at most. */
  detail?: ReactNode;
  /** At most one action. A good zero and a restricted page have none. */
  action?: { label: string; onClick: () => void };
}

/** An empty state (DESIGN.md 6.0): left-aligned at the top of the body, at most two lines
 * and one action, no illustration. The first line is an empty state heading of the type
 * scale (`text-md`, 600); a good zero is not a heading: it reads in normal text. */
export function EmptyState({ kind, title, detail, action }: EmptyStateProps) {
  // A heading where the page has something to say or do; a plain line for a good zero and
  // for a pane that only waits for a choice ("Pick an alert.").
  const tone =
    kind === "good-zero"
      ? "text-text"
      : kind === "default-empty"
        ? "text-text-secondary"
        : "text-md text-text";
  const mayAct = kind === "not-set-up" || kind === "filtered";
  return (
    <div data-empty={kind} className="flex flex-col items-start gap-1 px-3 py-3 text-sm">
      <p className={tone}>{title}</p>
      {detail ? <p className="text-text-secondary">{detail}</p> : null}
      {action && mayAct ? (
        <button
          type="button"
          onClick={action.onClick}
          className="h-7 rounded border border-border-strong px-2.5 text-text hover:bg-surface-head"
        >
          {action.label}
        </button>
      ) : null}
    </div>
  );
}
