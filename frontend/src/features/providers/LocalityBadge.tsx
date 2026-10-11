interface LocalityBadgeProps {
  locality: "local" | "cloud";
  /** False when the server could not resolve the host; the reason it counts as cloud. */
  hostFound?: boolean;
}

/** Where a provider's calls go, as the server computed it from the URL (SPEC 6.1). */
export function LocalityBadge({ locality, hostFound = true }: LocalityBadgeProps) {
  if (locality === "local") {
    return (
      <span className="rounded-badge bg-local-bg px-2 py-px text-xs text-local-text">Local</span>
    );
  }
  return (
    <span className="flex flex-col items-start gap-0.5">
      <span className="rounded-badge bg-cloud-bg px-2 py-px text-xs text-cloud-text">Cloud</span>
      {hostFound ? null : (
        <span className="text-xs text-text-secondary">
          Host not found, so treated as cloud until it resolves
        </span>
      )}
    </span>
  );
}
