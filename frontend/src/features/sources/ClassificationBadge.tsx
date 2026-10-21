interface ClassificationBadgeProps {
  value: "local_only" | "cloud_allowed";
}

export function ClassificationBadge({ value }: ClassificationBadgeProps) {
  return value === "local_only" ? (
    <span className="rounded-badge bg-local-bg px-2 py-px text-xs text-local-text">Local only</span>
  ) : (
    <span className="rounded-badge bg-cloud-bg px-2 py-px text-xs text-cloud-text">
      Cloud allowed
    </span>
  );
}
