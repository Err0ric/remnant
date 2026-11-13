import { cn } from "@/lib/cn";

interface EventIdChipProps {
  id: string;
  /** What the chip shows; the full id is the title. */
  label: string;
  /** False when a cited id is not one of the events that were sent (citation check). */
  verified?: boolean;
  selected?: boolean;
  /** Makes the chip a real button that selects the cited event. */
  onSelect?: (id: string) => void;
  title?: string;
}

/** A cited event id (DESIGN.md 7): mono 12px on the Info pair; selected, the pressed fill
 * with a 1px accent border. An id that fails the citation check is outlined in the danger
 * color and never filled. */
export function EventIdChip({
  id,
  label,
  verified = true,
  selected = false,
  onSelect,
  title,
}: EventIdChipProps) {
  const cls = cn(
    "rounded-badge border px-1.5 py-px font-mono text-xs",
    !verified
      ? "border-danger text-danger"
      : selected
        ? "border-accent-text bg-accent-subtle text-text"
        : "border-transparent bg-info-bg text-info-tx",
  );
  if (!onSelect)
    return (
      <span data-event-id={id} className={cls} title={title ?? id}>
        {label}
      </span>
    );
  return (
    <button
      type="button"
      data-event-id={id}
      aria-pressed={selected}
      onClick={() => onSelect(id)}
      title={title ?? id}
      className={cn(cls, "cursor-pointer hover:border-accent-text")}
    >
      {label}
    </button>
  );
}
