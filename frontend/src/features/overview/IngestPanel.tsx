import type { Overview } from "@/lib/api";
import { navigate } from "@/lib/route";
import { SourceState } from "@/features/sources/SourceState";
import { Panel } from "./Panel";
import { since } from "./time";

interface IngestPanelProps {
  overview: Overview;
}

/** Each readable source: state, when it last received an event, and anything waiting or skipped. */
export function IngestPanel({ overview }: IngestPanelProps) {
  const errors = overview.sources.filter((s) => s.state === "error").length;
  const quiet = overview.sources.filter((s) => s.quiet_since).length;
  const meta = [errors ? `${errors} with errors` : "", quiet ? `${quiet} quiet` : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <Panel title="Ingest health" meta={meta || `${overview.sources.length} sources`}>
      {overview.sources.length === 0 ? (
        <div className="flex flex-col items-start gap-1">
          <p className="text-text-secondary">No sources you can read yet.</p>
          <button
            type="button"
            className="rounded px-2 py-1 text-accent-text hover:bg-surface-head"
            onClick={() => navigate("sources")}
          >
            Go to Sources
          </button>
        </div>
      ) : (
        <ul className="flex flex-col">
          {overview.sources.map((s) => (
            <li
              key={s.source_id}
              className="flex flex-wrap items-start gap-x-3 gap-y-1 border-t border-border py-1.5 first:border-0"
            >
              <span title={s.source_id} className="min-w-[8rem] flex-1 truncate font-mono">
                {s.source_id}
              </span>
              <SourceState status={{ ...s, files: 0, last_pass_at: null, events_since_start: 0 }} />
              {s.quiet_since ? <span className="text-warn">Quiet</span> : null}
              <span
                className={`w-28 text-right ${s.quiet_since ? "text-warn" : "text-text-secondary"}`}
              >
                {s.last_event_at
                  ? `Received ${since(s.last_event_at, overview.generated_at)}`
                  : "Nothing received in 7 days"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
