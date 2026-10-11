import { useState } from "react";
import { ApiError, api, type Overview, type OverviewDetection } from "@/lib/api";
import { navigate } from "@/lib/route";
import { eventsSql, seedSearch } from "@/lib/searchSeed";
import { LevelBadge } from "@/features/detect/LevelBadge";
import { Panel } from "./Panel";
import { stamp } from "./time";

interface DetectionsPanelProps {
  overview: Overview;
}

/** Rule runs with matches and flagged saved-search runs in the last 24 hours. */
export function DetectionsPanel({ overview }: DetectionsPanelProps) {
  const [error, setError] = useState<string | null>(null);

  const open = async (d: OverviewDetection) => {
    setError(null);
    if (d.kind === "search") {
      navigate("dashboard"); // the schedule's panel has the rows and Open in Search
      return;
    }
    try {
      const matches = await api.ruleMatches(d.run_id);
      seedSearch({ sql: eventsSql(matches.map((m) => m.event_id)) });
      navigate("search");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not open the matches");
    }
  };

  return (
    <Panel title="Detections" meta="last 24 hours">
      {overview.detections.length === 0 ? (
        <p className="text-text-secondary">
          No rule matches or flagged searches in the last 24 hours.
        </p>
      ) : (
        <ul className="flex flex-col">
          {overview.detections.map((d) => (
            <li
              key={d.run_id}
              className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-border py-1.5 first:border-0"
            >
              {d.kind === "rule" ? (
                <LevelBadge level={d.level ?? ""} />
              ) : (
                <span className="rounded-badge bg-sev-high-bg px-2 py-px text-xs text-sev-high-text">
                  Flagged
                </span>
              )}
              <button
                type="button"
                className="min-w-0 flex-1 truncate text-left text-accent-text hover:underline"
                title={d.reason ?? d.name}
                onClick={() => void open(d)}
              >
                {d.name}
              </button>
              <span className="font-mono tabular-nums">
                {d.count.toLocaleString()} {d.kind === "rule" ? "matches" : "rows"}
              </span>
              <span className="w-full text-text-muted sm:w-auto">{stamp(d.started_at)}</span>
            </li>
          ))}
        </ul>
      )}
      {error ? (
        <p role="alert" className="text-danger">
          {error}
        </p>
      ) : null}
    </Panel>
  );
}
