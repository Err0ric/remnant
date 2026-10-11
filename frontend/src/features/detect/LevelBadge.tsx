const TONES: Record<string, string> = {
  critical: "bg-sev-critical-bg text-sev-critical-text",
  high: "bg-sev-high-bg text-sev-high-text",
  medium: "bg-sev-medium-bg text-sev-medium-text",
  low: "bg-sev-low-bg text-sev-low-text",
  informational: "bg-sev-info-bg text-sev-info-text",
};

interface LevelBadgeProps {
  /** A Sigma rule level; anything else is shown muted as written. */
  level: string;
}

export function LevelBadge({ level }: LevelBadgeProps) {
  const tone = TONES[level.toLowerCase()];
  if (!level) return <span className="text-text-muted">·</span>;
  return (
    <span className={`rounded-badge px-2 py-px text-xs ${tone ?? TONES.informational}`}>
      {level}
    </span>
  );
}
