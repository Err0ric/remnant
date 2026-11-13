import { SeverityMark, severityTone } from "@/components/SeverityMark";
import { SEVERITY } from "@/lib/search";

interface SeverityBadgeProps {
  value: unknown;
}

/** An OCSF `severity_id` as its mark and label. */
export function SeverityBadge({ value }: SeverityBadgeProps) {
  const sev = typeof value === "number" ? SEVERITY[value] : undefined;
  if (!sev) return <span className="text-text-muted">·</span>;
  return <SeverityMark tone={severityTone(sev.tone)} label={sev.label} />;
}
