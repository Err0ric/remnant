const TONES: Record<string, string> = {
  success: "bg-sev-info-bg text-text-secondary",
  failure: "bg-sev-critical-bg text-sev-critical-text",
  denied: "bg-sev-high-bg text-sev-high-text",
  blocked: "bg-sev-high-bg text-sev-high-text",
};

interface OutcomeBadgeProps {
  outcome: string;
  label?: string;
}

/** Outcome as text in a tinted badge; never color alone. */
export function OutcomeBadge({ outcome, label }: OutcomeBadgeProps) {
  return (
    <span className={`rounded-badge px-2 py-px text-xs ${TONES[outcome] ?? TONES.success}`}>
      {label ?? outcome}
    </span>
  );
}
