import type { ReactNode } from "react";
import type { Overview, Schedule } from "@/lib/api";
import { since, stamp } from "@/features/overview/time";
import { changeText } from "./flow";

export interface SourceTally {
  total: number;
  healthy: number;
  gaps: number;
  worstLag: string | null;
  worstLagSource: string | null;
}

interface TileProps {
  label: string;
  value: ReactNode;
  lines: ReactNode[];
  tone?: "ok" | "warn" | "danger";
  onClick: () => void;
  title?: string;
}

const TONE = { ok: "text-ok", warn: "text-warn", danger: "text-danger" };

function Tile({ label, value, lines, tone, onClick, title }: TileProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="flex min-w-0 flex-col items-start gap-0.5 rounded-card border border-border bg-surface px-4 py-3 text-left hover:bg-surface-head"
    >
      <span className="text-sm text-text-secondary">{label}</span>
      <span className={`text-kpi tabular-nums ${tone ? TONE[tone] : ""}`}>{value}</span>
      {lines.map((l, i) => (
        <span key={i} className="w-full text-sm text-text-secondary [overflow-wrap:anywhere]">
          {l}
        </span>
      ))}
    </button>
  );
}

interface SystemStripProps {
  overview: Overview | undefined;
  tally: SourceTally;
  attention: Schedule[];
  isAdmin: boolean;
  now: string;
  onEvents: () => void;
  onSources: () => void;
  onAttention: () => void;
  onDelivery: () => void;
}

/** Health's four answers (F55): is data arriving, is every source flowing, is anything
 * flagged, and do alerts get out. Each tile opens the detail behind it. */
export function SystemStrip(p: SystemStripProps) {
  const o = p.overview;
  const change = o ? changeText(o.events_24h, o.events_usual_24h) : null;
  const newest = p.attention[0];
  const failed = o?.alerts?.failed_deliveries ?? 0;
  const failing = (o?.alerts?.targets ?? []).filter((t) => t.failing);
  const sourcesOk = p.tally.healthy === p.tally.total && p.tally.gaps === 0;
  return (
    <div
      className={`grid grid-cols-1 gap-3 sm:grid-cols-2 ${p.isAdmin ? "xl:grid-cols-4" : "xl:grid-cols-3"}`}
    >
      <Tile
        label="Events, last 24 hours"
        value={o ? o.events_24h.toLocaleString() : "·"}
        lines={[change ?? "No earlier days to compare yet"]}
        title={o ? `Up to ${stamp(o.generated_at)} UTC` : undefined}
        onClick={p.onEvents}
      />
      <Tile
        label="Sources"
        value={
          <>
            {p.tally.healthy}
            <span className="text-base font-normal text-text-secondary">
              {" "}
              of {p.tally.total} healthy
            </span>
          </>
        }
        tone={sourcesOk ? undefined : "warn"}
        lines={[
          p.tally.gaps
            ? `${p.tally.gaps} ${p.tally.gaps === 1 ? "gap" : "gaps"} in 24 hours`
            : "No gaps in 24 hours",
          p.tally.worstLag
            ? `Longest wait: ${p.tally.worstLag} (${p.tally.worstLagSource})`
            : "No events yet",
        ]}
        onClick={p.onSources}
      />
      <Tile
        label="Needs attention"
        value={p.attention.length}
        tone={p.attention.length ? "warn" : undefined}
        lines={[
          newest
            ? `Newest: ${newest.name}${newest.recent[0] ? `, ${since(newest.recent[0].started_at, p.now)}` : ""}`
            : "Nothing flagged on your dashboards",
        ]}
        onClick={p.onAttention}
      />
      {p.isAdmin ? (
        <Tile
          label="Alert delivery, last 24 hours"
          value={failed ? failed : "All delivered"}
          tone={failed || failing.length ? "danger" : undefined}
          lines={[
            failing.length
              ? `Failing: ${failing.map((t) => t.name).join(", ")}`
              : failed
                ? "Retried; check the targets"
                : "No failed deliveries",
          ]}
          onClick={p.onDelivery}
        />
      ) : null}
    </div>
  );
}
