import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ExplainPanel } from "@/features/explain/ExplainPanel";
import { api, type RuleRun } from "@/lib/api";
import { navigate } from "@/lib/route";
import { eventsSql, seedSearch } from "@/lib/searchSeed";
import { LevelBadge } from "./LevelBadge";
import { authorText } from "./rules";

const STATUS: Record<RuleRun["status"], string> = {
  ok: "Finished",
  no_data: "No matching sources",
  failed: "Failed",
};

interface RunPanelProps {
  run: RuleRun;
  onClose: () => void;
  /** Admins and analysts may send matches to a model; auditors have no AI features. */
  canExplain?: boolean;
}

/** One run and its matches. Title and author are shown with every match (DRL 1.1). */
export function RunPanel({ run, onClose, canExplain = false }: RunPanelProps) {
  const [explaining, setExplaining] = useState(false);
  const matches = useQuery({
    queryKey: ["rule-matches", run.run_id],
    queryFn: () => api.ruleMatches(run.run_id),
    enabled: run.matches_stored > 0,
  });
  const rows = matches.data ?? [];

  return (
    <section
      aria-label="Rule run"
      className="flex flex-col gap-2 rounded-card border border-border bg-surface p-3 text-sm"
    >
      <div className="flex flex-wrap items-center gap-2">
        <LevelBadge level={run.level} />
        <span className="font-semibold">{run.title}</span>
        <span className="text-text-secondary">by {authorText(run.author)}</span>
        <button
          type="button"
          className="ml-auto rounded px-2 py-1 hover:bg-surface-head"
          onClick={onClose}
        >
          Close
        </button>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-text-secondary">
        <span>{STATUS[run.status]}</span>
        <span>
          {run.match_count} {run.match_count === 1 ? "match" : "matches"}
          {run.match_count > run.matches_stored ? ` (first ${run.matches_stored} kept)` : ""}
        </span>
        <span className="font-mono">
          {run.range_start.slice(0, 16)} to {run.range_end.slice(0, 16)} UTC
        </span>
        <span>
          Sources read:{" "}
          <span className="font-mono">
            {run.sources_in_scope.length ? run.sources_in_scope.join(", ") : "none"}
          </span>
        </span>
        <span>{run.elapsed_ms} ms</span>
      </div>
      {run.status === "no_data" ? (
        <p className="text-text-secondary">
          No source you can read has a template declaring this rule&apos;s log source.
        </p>
      ) : null}
      {run.error ? (
        <p role="alert" className="text-danger">
          {run.error}
        </p>
      ) : null}
      {rows.length ? (
        <>
          <div className="max-h-80 overflow-auto rounded border border-border">
            <table aria-label="Matches" className="w-full">
              <thead>
                <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
                  <th className="px-2 py-1 font-semibold">Time</th>
                  <th className="px-2 py-1 font-semibold">Source</th>
                  <th className="px-2 py-1 font-semibold">Event id</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((m) => (
                  <tr key={m.event_id} className="border-b border-border last:border-0">
                    <td className="px-2 py-1 font-mono">{m.event_time ?? "·"}</td>
                    <td className="px-2 py-1 font-mono">{m.source_id}</td>
                    <td className="px-2 py-1 font-mono">{m.event_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="h-8 rounded border border-border px-3 text-accent-text hover:bg-surface-head"
              onClick={() => {
                seedSearch({ sql: eventsSql(rows.map((m) => m.event_id)) });
                navigate("search");
              }}
            >
              Open in Search
            </button>
            {canExplain ? (
              <button
                type="button"
                className="h-8 rounded border border-border px-3 hover:bg-surface-head"
                onClick={() => setExplaining(true)}
              >
                Explain matches
              </button>
            ) : null}
          </div>
          {explaining ? (
            <ExplainPanel
              eventIds={rows.map((m) => m.event_id)}
              subject={`matches of ${run.title}`}
              onClose={() => setExplaining(false)}
            />
          ) : null}
        </>
      ) : null}
    </section>
  );
}
