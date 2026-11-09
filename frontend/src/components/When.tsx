import { stamp } from "@/features/overview/time";
import { zoneIfRepeated } from "@/lib/localTime";

interface WhenProps {
  iso: string | null | undefined;
  /** For tests; the viewer's zone otherwise. */
  timeZone?: string;
  className?: string;
  /** "9:05:01 AM": log tables keep the seconds, so events in one minute read apart. */
  seconds?: boolean;
}

/** "Oct 22, 2:05 AM" in the viewer's time zone, with the UTC time on hover: the one way
 * a time is shown (DESIGN consistency rule; product pass). In an hour that happens twice
 * it adds the zone: "Nov 1, 1:15 AM PDT" and "Nov 1, 1:15 AM PST". */
export function When({ iso, timeZone, className, seconds = false }: WhenProps) {
  if (!iso) return <span className={className}>·</span>;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return <span className={className}>{iso}</span>;
  const text = d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: seconds ? "2-digit" : undefined,
    timeZone,
  });
  // In a repeated hour (clocks falling back) the zone tells the two readings apart.
  const zone = zoneIfRepeated(d, timeZone);
  return (
    <time dateTime={iso} title={`${stamp(iso)} UTC`} className={className}>
      {text}
      {zone}
    </time>
  );
}
