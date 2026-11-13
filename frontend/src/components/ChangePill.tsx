import { cn } from "@/lib/cn";

interface ChangePillProps {
  /** This period minus the one before. */
  change: number;
  /** What a screen reader says in place of the arrow and number. */
  spoken: string;
  title?: string;
  /** Opens the period before (a drill into Logs); without it the pill is plain text. */
  onOpen?: () => void;
}

/** The change beside a KPI value (DESIGN.md 7): a neutral pill with an arrow and the amount,
 * or "same". Never green or red: more is not good or bad by itself. */
export function ChangePill({ change, spoken, title, onOpen }: ChangePillProps) {
  const cls =
    "rounded-badge border border-border bg-surface-head px-1.5 font-mono text-xs font-semibold tabular-nums text-text";
  const body = (
    <>
      <span aria-hidden="true">
        {change === 0 ? "same" : `${change > 0 ? "↑" : "↓"} ${Math.abs(change).toLocaleString()}`}
      </span>
      <span className="sr-only">{spoken}</span>
    </>
  );
  if (!onOpen)
    return (
      <span data-change="" className={cls} title={title}>
        {body}
      </span>
    );
  return (
    <button
      type="button"
      data-change=""
      data-drill=""
      onClick={onOpen}
      title={title}
      className={cn(
        cls,
        "cursor-pointer hover:bg-border focus-visible:outline focus-visible:outline-1 focus-visible:outline-focus-ring",
      )}
    >
      {body}
    </button>
  );
}
