import { SeverityMark, severityTone } from "@/components/SeverityMark";

interface LevelBadgeProps {
  /** A Sigma rule level; anything else is shown neutral, as written. */
  level: string;
}

export function LevelBadge({ level }: LevelBadgeProps) {
  if (!level) return <span className="text-text-muted">·</span>;
  return <SeverityMark tone={severityTone(level)} label={level} />;
}
