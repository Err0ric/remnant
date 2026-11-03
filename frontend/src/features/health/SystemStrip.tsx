import type { ReactNode } from "react";
import type { AlertList, Overview } from "@/lib/api";
import { since, stamp } from "@/features/overview/time";
import { eventsChange } from "./flow";
import { COUNTED } from "@/features/dashboard/counted";
import { About } from "@/features/dashboard/Sections";

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
  /** How the number is counted; required for every tile (owner 2026-11-02). */
  about: string;
}

// Benign values are muted, never green: status colors are for what needs action (DESIGN.md).
const TONE = { ok: "text-text-muted", warn: "text-warn", danger: "text-danger" };

function Tile({ label, value, lines, tone, onClick, title, about }: TileProps) {
  return (
    <button
      type="button"
      data-kpi={label}
      onClick={onClick}
      title={title}
      className="flex min-w-0 flex-col items-start gap-0.5 rounded-card border border-border bg-surface px-4 py-3 text-left hover:bg-surface-head"
    >
      <span className="flex items-center gap-1.5 text-sm text-text-secondary">
        {label}
        <About text={about} />
      </span>
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
  /** Open alerts the viewer may read (ADR-0037). */
  alerts: AlertList | undefined;
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
  const change = o ? eventsChange(o) : null;
  const newest = p.alerts?.items[0];
  const open = p.alerts?.open ?? 0;
  const failed = o?.alerts?.failed_deliveries ?? 0;
  const failing = (o?.alerts?.targets ?? []).filter((t) => t.failing);
  const sourcesOk = p.tally.healthy === p.tally.total && p.tally.gaps === 0;
  return (
    <div
      className={`grid grid-cols-1 gap-3 sm:grid-cols-2 ${p.isAdmin ? "xl:grid-cols-4" : "xl:grid-cols-3"}`}
    >
      <Tile
        label="Events, last 24 hours"
        about={COUNTED.events24h}
        value={o ? o.events_24h.toLocaleString() : "·"}
        lines={[change ?? ""]}
        title={o ? `Up to ${stamp(o.generated_at)} UTC` : undefined}
        onClick={p.onEvents}
      />
      <Tile
        label="Sources"
        about={COUNTED.sourcesHealthy}
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
        label="Open alerts"
        about={COUNTED.openAlerts}
        value={p.alerts ? open : "·"}
        tone={open ? "warn" : undefined}
        lines={[
          newest
            ? `Newest: ${newest.title}, ${since(newest.created_at, p.now)}`
            : "Nothing needs a decision",
        ]}
        onClick={p.onAttention}
      />
      {p.isAdmin ? (
        <Tile
          label="Alert delivery, last 24 hours"
          about={COUNTED.delivery}
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
