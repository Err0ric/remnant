import { stamp } from "@/features/overview/time";

interface LateBadgeProps {
  late: boolean | undefined;
  start: string | null | undefined;
  end: string | null | undefined;
}

/** An alert raised or grown by a rule re-run over reparsed events (D241): it was found
 * late. The events' time range is on hover, in UTC; the alert's page shows it in full. */
export function LateBadge({ late, start, end }: LateBadgeProps) {
  if (!late) return null;
  const title =
    start && end
      ? `Late detection from reparse: events ${stamp(start)} to ${stamp(end)} UTC`
      : "Late detection from reparse";
  return (
    <span
      title={title}
      className="shrink-0 rounded-badge bg-surface-head px-1.5 py-px text-xs text-text-secondary"
    >
      Late
    </span>
  );
}
