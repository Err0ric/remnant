import type { AlertList, Overview, SourceSummary } from "@/lib/api";
import { KpiTile } from "@/components/KpiTile";
import { since, stamp } from "@/features/overview/time";
import { eventsChange, sourcesSummaryText, type OpenGap } from "./flow";
import { COUNTED } from "@/features/dashboard/counted";

export interface SourceTally {
  /** Counted once on the server, the same the Dashboard footer shows (handoff item 4). */
  summary: SourceSummary;
  /** Sources with an open gap alert or a firing quiet watch (review item 3). */
  openGaps?: OpenGap[];
}

interface SystemStripProps {
  overview: Overview | undefined;
  /** Not counted (an overview without a summary): the tile shows a dot. */
  tally: SourceTally | undefined;
  /** Open alerts the viewer may read (ADR-0037). */
  alerts: Pick<AlertList, "items" | "open"> | undefined;
  /** The overview read failed: its tiles say so, with Retry, instead of loading for ever. */
  overviewFailed?: () => void;
  /** The newest-alert read failed. */
  alertsFailed?: () => void;
  isAdmin: boolean;
  now: string;
}

/** Health's four answers (F55): is data arriving, is every source flowing, is anything
 * flagged, and do alerts get out. One strip of Dashboard tiles (D255): each leads with a
 * number in the text color, the Sources count in the warn color when not all are healthy,
 * and a tile whose data is still loading shows bars, never a zero or an all-clear. */
export function SystemStrip(p: SystemStripProps) {
  const o = p.overview;
  const newest = p.alerts?.items[0];
  const failed = o?.alerts?.failed_deliveries ?? 0;
  const failing = (o?.alerts?.targets ?? []).filter((t) => t.failing);
  const sum = p.tally?.summary;
  const sourcesOk = !sum || (sum.healthy === sum.total && sum.gaps === 0);
  // The same words as the Dashboard footer, on one line: "2 quiet: ...; no gaps in 24 hours".
  const sourceLine = sum
    ? sourcesSummaryText(sum, o?.generated_at ?? p.now).details.join("; ")
    : "";
  return (
    <section
      aria-label="Health numbers"
      className={`grid grid-cols-1 gap-px overflow-hidden rounded-card border border-border bg-border sm:grid-cols-2 ${p.isAdmin ? "xl:grid-cols-4" : "xl:grid-cols-3"}`}
    >
      <KpiTile
        label="Events, last 24 hours"
        about={COUNTED.events24h}
        loading={!o && !p.overviewFailed}
        failed={o ? undefined : p.overviewFailed}
        value={o?.events_24h.toLocaleString()}
        context={o ? eventsChange(o) : null}
        title={o ? `Up to ${stamp(o.generated_at)} UTC` : undefined}
        page="logs"
        opens="Logs"
      />
      <KpiTile
        label="Sources healthy"
        about={COUNTED.sourcesHealthy}
        loading={!o && !p.overviewFailed}
        failed={o ? undefined : p.overviewFailed}
        value={sum ? `${sum.healthy.toLocaleString()} of ${sum.total.toLocaleString()}` : "·"}
        tone={sourcesOk ? "text" : "warn"}
        context={sourceLine.charAt(0).toUpperCase() + sourceLine.slice(1)}
        page="health"
        tab="sources"
        opens="the Sources tab"
      />
      <KpiTile
        label="Open alerts"
        about={COUNTED.openAlerts}
        loading={!p.alerts && !p.alertsFailed}
        failed={p.alerts ? undefined : p.alertsFailed}
        value={(p.alerts?.open ?? 0).toLocaleString()}
        context={
          newest
            ? `Newest: ${newest.title}, ${since(newest.created_at, p.now)}`
            : "Nothing needs a decision"
        }
        page="alerts"
        opens="Alerts"
      />
      {p.isAdmin ? (
        <KpiTile
          label="Alert delivery, last 24 hours"
          about={COUNTED.delivery}
          loading={!o && !p.overviewFailed}
          failed={o ? undefined : p.overviewFailed}
          value={`${failed.toLocaleString()} failed`}
          context={
            failing.length
              ? `Failing: ${failing.map((t) => t.name).join(", ")}`
              : failed
                ? "Retried; check the targets"
                : "All delivered"
          }
          page="health"
          tab="delivery"
          opens="the Delivery tab"
        />
      ) : null}
    </section>
  );
}
