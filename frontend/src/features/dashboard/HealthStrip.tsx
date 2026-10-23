import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { navigate } from "@/lib/route";

/** Health on the Dashboard's first screen (ADR-0031): counts only, and a link to Health
 * for the detail. Gaps count too (F55): a source that stopped for hours is a problem. */
export function HealthStrip() {
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 60_000,
  });
  const o = overview.data;
  if (!o) return null;
  const behind = o.sources.filter((s) => s.state === "error").length;
  const quiet = o.sources.filter((s) => s.quiet_since).length;
  const failing = o.alerts?.targets.filter((t) => t.failing).length ?? 0;
  const gaps = o.volume.filter((v) => v.gaps.length > 0).length;
  const items: [number, string, string][] = [
    [behind, "source with errors", "sources with errors"],
    [gaps, "source with a gap in 24 hours", "sources with gaps in 24 hours"],
    [quiet, "quiet source", "quiet sources"],
    [o.paused.length, "paused schedule", "paused schedules"],
    [failing, "failing alert target", "failing alert targets"],
  ];
  const issues = items.filter(([n]) => n > 0);
  return (
    <section
      aria-label="Health"
      className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-card border border-border bg-surface px-3 py-2 text-sm"
    >
      <span className="font-semibold">Health</span>
      {issues.length === 0 ? (
        <span className="text-text-secondary">All sources, schedules, and alerts are healthy</span>
      ) : (
        issues.map(([n, one, many]) => (
          <span key={one} className="text-warn">
            <span className="font-mono tabular-nums">{n}</span> {n === 1 ? one : many}
          </span>
        ))
      )}
      <button
        type="button"
        className="ml-auto rounded px-1.5 py-0.5 text-accent-text hover:bg-surface-head"
        onClick={() => navigate("health", "sources")}
      >
        Open Health
      </button>
    </section>
  );
}
