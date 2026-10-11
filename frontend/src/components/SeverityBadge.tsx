import { SEVERITY } from "@/lib/search";

const TONES: Record<string, string> = {
  critical: "bg-sev-critical-bg text-sev-critical-text",
  high: "bg-sev-high-bg text-sev-high-text",
  medium: "bg-sev-medium-bg text-sev-medium-text",
  low: "bg-sev-low-bg text-sev-low-text",
  info: "bg-sev-info-bg text-sev-info-text",
};

interface SeverityBadgeProps {
  value: unknown;
}

export function SeverityBadge({ value }: SeverityBadgeProps) {
  const sev = typeof value === "number" ? SEVERITY[value] : undefined;
  if (!sev) return <span className="text-text-muted">·</span>;
  return (
    <span className={`rounded-badge px-2 py-px text-xs ${TONES[sev.tone] ?? TONES.info}`}>
      {sev.label}
    </span>
  );
}
