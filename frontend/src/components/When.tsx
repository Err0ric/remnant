import { stamp } from "@/features/overview/time";

interface WhenProps {
  iso: string | null | undefined;
  /** For tests; the viewer's zone otherwise. */
  timeZone?: string;
  className?: string;
}

/** "Oct 22, 2:05 AM" in the viewer's time zone, with the UTC time on hover: the one way
 * a time is shown (DESIGN consistency rule; product pass). */
export function When({ iso, timeZone, className }: WhenProps) {
  if (!iso) return <span className={className}>·</span>;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return <span className={className}>{iso}</span>;
  const text = d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  });
  return (
    <time dateTime={iso} title={`${stamp(iso)} UTC`} className={className}>
      {text}
    </time>
  );
}
