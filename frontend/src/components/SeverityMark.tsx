import { cn } from "@/lib/cn";

export type SeverityTone = "critical" | "high" | "medium" | "low" | "info";

const SOLID: Partial<Record<SeverityTone, string>> = {
  critical: "bg-sev-c-solid text-sev-c-on",
  high: "bg-sev-h-solid text-sev-h-on",
};
const DOT: Record<SeverityTone, string> = {
  critical: "bg-sev-c-solid",
  high: "bg-sev-h-solid",
  medium: "bg-sev-m-dot",
  low: "bg-text-muted",
  info: "bg-text-muted",
};

/** Maps a level as written (Sigma "informational", OCSF labels) to a tone. */
export function severityTone(level: string): SeverityTone {
  const l = level.toLowerCase();
  if (l === "critical" || l === "high" || l === "medium" || l === "low") return l;
  return "info";
}

interface SeverityMarkProps {
  tone: SeverityTone;
  /** Always shown: a severity is never color alone. */
  label: string;
  className?: string;
}

/** A severity (DESIGN.md sections 2 and 7): Critical and High are solid badges; Medium, Low,
 * and Info are a square dot and the label in the text color. Low and Info are neutral. */
export function SeverityMark({ tone, label, className }: SeverityMarkProps) {
  const solid = SOLID[tone];
  if (solid) {
    return (
      <span
        data-severity={tone}
        className={cn(
          "inline-block whitespace-nowrap rounded-badge px-1.5 text-xs font-semibold",
          solid,
          className,
        )}
      >
        {label}
      </span>
    );
  }
  return (
    <span
      data-severity={tone}
      className={cn("inline-flex items-center gap-1.5 whitespace-nowrap text-text", className)}
    >
      <span className={cn("h-[7px] w-[7px] shrink-0 rounded-[2px]", DOT[tone])} aria-hidden />
      {label}
    </span>
  );
}
