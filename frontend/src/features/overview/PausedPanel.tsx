import type { Overview } from "@/lib/api";
import { navigate } from "@/lib/route";
import { Panel } from "./Panel";

interface PausedPanelProps {
  overview: Overview;
}

/** Schedules you can see that are paused: each one is a gap in detection until resumed. */
export function PausedPanel({ overview }: PausedPanelProps) {
  return (
    <Panel title="Paused schedules" meta={`${overview.paused.length}`}>
      {overview.paused.length === 0 ? (
        <p className="text-text-secondary">Every schedule you can see is running.</p>
      ) : (
        <ul className="flex flex-col">
          {overview.paused.map((p) => (
            <li
              key={p.schedule_id}
              className="flex flex-col border-t border-border py-1.5 first:border-0"
            >
              <button
                type="button"
                className="truncate text-left text-accent-text hover:underline"
                onClick={() => navigate("schedules")}
              >
                {p.name}
              </button>
              <span className="text-warn">{p.reason ?? "Paused by a person"}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
