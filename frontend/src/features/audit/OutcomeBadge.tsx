const TONES: Record<string, string> = {
  success: "bg-info-bg text-text-secondary",
  failure: "border border-danger text-danger",
  denied: "border border-warn text-warn",
  // A gate block is an error color (DESIGN.md 2), like a failure.
  blocked: "border border-danger text-danger",
};

interface OutcomeBadgeProps {
  outcome: string;
  label?: string;
}

/** Outcome as text in a tag (outlined for a problem); never color alone. */
export function OutcomeBadge({ outcome, label }: OutcomeBadgeProps) {
  return (
    <span className={`rounded-badge px-2 py-px text-xs ${TONES[outcome] ?? TONES.success}`}>
      {label ?? outcome}
    </span>
  );
}
