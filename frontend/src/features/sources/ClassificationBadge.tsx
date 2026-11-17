interface ClassificationBadgeProps {
  value: "local_only" | "cloud_allowed";
}

export function ClassificationBadge({ value }: ClassificationBadgeProps) {
  return value === "local_only" ? (
    <span className="whitespace-nowrap rounded-badge bg-local-bg px-2 py-px text-xs text-local-tx">
      Local only
    </span>
  ) : (
    <span className="whitespace-nowrap rounded-badge bg-cloud-bg px-2 py-px text-xs text-cloud-tx">
      Cloud allowed
    </span>
  );
}
