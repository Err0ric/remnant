import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api, type AlertKind, type AlertMetrics, type AlertSeverityKey } from "@/lib/api";
import { Card } from "@/components/Card";
import { CardAction } from "@/components/CardAction";
import { FilterBar } from "@/components/FilterBar";
import { InlineError } from "@/components/InlineError";
import { KpiTile } from "@/components/KpiTile";
import { SeverityMark } from "@/components/SeverityMark";
import { Skeleton } from "@/components/Skeleton";
import { StateNotice } from "@/components/StateNotice";
import { PageHeader } from "@/components/shell/PageHeader";
import { TrendChart, TrendLegend } from "@/features/dashboard/TrendChart";
import { navigate } from "@/lib/route";
import { usePageTime } from "@/lib/timeChoice";
import { CATEGORY_LABEL, type Category } from "./guide";
import { RESTRICTED_NOTE } from "./kinds";

/** "under a minute", "45 min", "3 h 5 min", "2 d 4 h": a time to close in plain words. */
export function plainDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  if (m < 1) return "under a minute";
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
  const d = Math.floor(h / 24);
  return h % 24 ? `${d} d ${h % 24} h` : `${d} d`;
}

const SEVERITIES: { key: AlertSeverityKey; label: string; filter: string }[] = [
  { key: "high", label: "High", filter: "high" },
  { key: "medium", label: "Medium", filter: "medium" },
  { key: "other", label: "None", filter: "none" },
];
const KINDS: { kind: AlertKind; category: Category }[] = [
  { kind: "rule", category: "detection" },
  { kind: "schedule", category: "search" },
  { kind: "ai_watch", category: "ai" },
  { kind: "gap", category: "gap" },
];

/** The overdue days an alert of this severity has: no severity uses Low (D261). */
export function overdueDays(m: AlertMetrics, sev: AlertSeverityKey): number {
  return sev === "other" ? m.thresholds.low : m.thresholds[sev];
}

const known = (v: number | null | undefined): v is number => v !== null && v !== undefined;
const days = (n: number) => `${n} ${n === 1 ? "day" : "days"}`;
const dayLabel = (day: string) =>
  new Date(`${day}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });

/** The Queue's fragment for alerts closed in the window the server used: a preset as it
 * is, and Custom always with both ends from the answer, since an open side means "every
 * close kept" to the Queue but 30 days before the end to the server. */
export function closedIn(used: { start: string; end: string }, preset: string): string {
  const q = new URLSearchParams({ state: "closed", time: preset });
  if (preset === "custom") {
    q.set("from", new Date(used.start).toISOString());
    q.set("to", new Date(used.end).toISOString());
  }
  return q.toString();
}

const moment = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

/** "in the last 30 days", or for Custom the window the server used: "from Nov 1, 8:00 AM to
 * Nov 14, 2:00 PM", so a side left open never reads as everything kept. */
export function windowWords(used: { start: string; end: string }, preset: string, words: string) {
  return preset === "custom" ? `from ${moment(used.start)} to ${moment(used.end)}` : `in ${words}`;
}

const ABOUT = {
  median:
    "Half of the alerts a person closed in this window were closed within this time, counted from when each was first raised to its latest close. Alerts the server closed, alerts with no close time kept, and alerts closed as Muted or Merged are not counted.",
  p90: "Nine in ten of the alerts a person closed in this window were closed within this time, counted the same way as the median.",
  overdue:
    "Open alerts raised longer ago than the days set for their severity (alerts with no severity use the Low setting). Set in the server's configuration under alerts.",
  open: "Every open alert you can read now, whatever the time window. The Queue counts at most its newest 200, so above that its count is lower.",
  chart:
    "Alerts first raised each day, and alerts closed each day by a person or by the server, in the install's time zone. Alerts closed as Muted or Merged are not counted; a reopened alert counts by its latest close.",
};

/** Alerts > Handling (D261, BACKLOG P2): whether alerts are being handled. Time to close,
 * opened against closed by day, and what is open and overdue now, for the alerts the
 * Queue shows this person. Observes only; nothing is enforced. */
export function HandlingPage() {
  const time = usePageTime("30d");
  const q = useQuery({
    queryKey: ["alerts", "metrics", ...time.key],
    queryFn: () => api.alertMetrics(time.bounds()),
  });
  const m = q.data;
  const loading = q.isLoading;
  const failed = !m && q.isError ? () => void q.refetch() : undefined;
  const toClosed = () => (m ? closedIn(m, time.choice.preset) : undefined);
  const span = m ? windowWords(m, time.choice.preset, time.words) : "";
  const ttc = m?.time_to_close;
  const overdueLine = m
    ? SEVERITIES.filter((s) => m.overdue_by_severity[s.key] > 0)
        .map(
          (s) => `${s.label} ${m.overdue_by_severity[s.key]} (over ${days(overdueDays(m, s.key))})`,
        )
        .join(", ")
    : "";
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader title="Alert handling" />
      <div className="flex min-w-0 flex-col gap-3 px-5 py-4">
        <FilterBar label="Filter alert handling" time={time.bar} isDefault={time.isDefault} />
        {m?.restricted ? <StateNotice>{RESTRICTED_NOTE}</StateNotice> : null}
        {q.isError && !m ? (
          <div className="rounded-card border border-border bg-surface">
            <InlineError
              what="Alert handling"
              error={q.error}
              onRetry={() => void q.refetch()}
              retrying={q.isFetching}
            />
          </div>
        ) : null}
        <section
          aria-label="Alert handling numbers"
          className="grid grid-cols-1 gap-px overflow-hidden rounded-card border border-border bg-border sm:grid-cols-2 xl:grid-cols-4"
        >
          <KpiTile
            label="Time to close, median"
            about={ABOUT.median}
            loading={loading}
            failed={failed}
            value={ttc && known(ttc.median_s) ? plainDuration(ttc.median_s) : "None closed"}
            tone={known(ttc?.median_s) ? "text" : "muted"}
            context={ttc ? `${ttc.count.toLocaleString()} closed by a person ${span}` : null}
            page={ttc?.count ? "alerts" : undefined}
            tab={toClosed()}
            opens="the alerts closed in this window"
          />
          <KpiTile
            label="Time to close, 90th percentile"
            about={ABOUT.p90}
            loading={loading}
            failed={failed}
            value={ttc && known(ttc.p90_s) ? plainDuration(ttc.p90_s) : "None closed"}
            tone={known(ttc?.p90_s) ? "text" : "muted"}
            context={
              m
                ? `${m.closed_not_timed.toLocaleString()} closed by the server or with no close time, not counted`
                : null
            }
            page={ttc?.count ? "alerts" : undefined}
            tab={toClosed()}
            opens="the alerts closed in this window"
          />
          <KpiTile
            label="Overdue now"
            about={ABOUT.overdue}
            loading={loading}
            failed={failed}
            value={(m?.overdue ?? 0).toLocaleString()}
            tone={m && m.overdue > 0 ? "warn" : "muted"}
            context={m ? overdueLine || "No open alert is past its days" : null}
          />
          <KpiTile
            label="Open now"
            about={ABOUT.open}
            loading={loading}
            failed={failed}
            value={(m?.open ?? 0).toLocaleString()}
            tone={m && m.open > 0 ? "text" : "muted"}
            context={
              m
                ? `${m.opened.toLocaleString()} opened, ${m.closed.toLocaleString()} closed ${span}`
                : null
            }
            page={m && m.open > 0 ? "alerts" : undefined}
            opens="the Queue"
          />
        </section>
        <div className="grid min-w-0 items-stretch gap-3 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <Card
            title="Opened and closed"
            about={ABOUT.chart}
            note={m ? `By day, ${m.timezone}` : undefined}
          >
            <div className="p-3">
              {m ? (
                <TrendChart
                  bare
                  title="Opened and closed"
                  summary={`Alerts opened and closed per day: ${m.opened} opened, ${m.closed} closed`}
                  series={[
                    {
                      key: "opened",
                      label: "Opened",
                      values: m.days.map((d) => d.opened),
                      color: "text-secondary",
                    },
                    {
                      key: "closed",
                      label: "Closed",
                      values: m.days.map((d) => d.closed),
                      color: "ok",
                    },
                  ]}
                  pointLabel={(i) => dayLabel(m.days[i]?.day ?? "")}
                  axisLabel={(i) => dayLabel(m.days[i]?.day ?? "")}
                  partial={time.choice.preset === "custom" ? undefined : "so far"}
                  legend={
                    <TrendLegend
                      items={[
                        { label: `Opened ${m.opened.toLocaleString()}`, color: "text-secondary" },
                        { label: `Closed ${m.closed.toLocaleString()}`, color: "ok" },
                      ]}
                    />
                  }
                />
              ) : failed ? (
                <NotLoaded />
              ) : (
                <Skeleton label="the chart" block="h-[164px]" className="rounded-none border-0" />
              )}
            </div>
          </Card>
          <Card
            title="Open by kind"
            action={<CardAction onClick={() => navigate("alerts")}>View all</CardAction>}
          >
            {m ? (
              <CountTable
                label="Open alerts by kind"
                head={["Kind", "Open now"]}
                rows={KINDS.map(({ kind, category }) => ({
                  key: kind,
                  name: CATEGORY_LABEL[category],
                  cells: [
                    <CountLink
                      key="n"
                      n={m.open_by_kind[kind]}
                      to={`cat=${category}`}
                      what={CATEGORY_LABEL[category]}
                    />,
                  ],
                }))}
              />
            ) : failed ? (
              <NotLoaded />
            ) : (
              <Skeleton
                label="open alerts by kind"
                rows={4}
                header
                className="rounded-none border-0"
              />
            )}
          </Card>
        </div>
        <Card title="By severity" note={m ? `Closes ${span}` : undefined}>
          {m ? (
            <CountTable
              label="Alerts by severity"
              head={[
                "Severity",
                "Open now",
                "Overdue after",
                "Overdue now",
                "Closed by a person",
                "Median",
                "90th percentile",
              ]}
              rows={SEVERITIES.map((s) => {
                const t = m.time_to_close_by_severity[s.key];
                return {
                  key: s.key,
                  name: s.key === "other" ? "None" : <SeverityMark tone={s.key} label={s.label} />,
                  cells: [
                    <CountLink
                      key="o"
                      n={m.open_by_severity[s.key]}
                      to={`sev=${s.filter}`}
                      what={`${s.label} severity`}
                    />,
                    days(overdueDays(m, s.key)),
                    m.overdue_by_severity[s.key].toLocaleString(),
                    t.count.toLocaleString(),
                    known(t.median_s) ? plainDuration(t.median_s) : "·",
                    known(t.p90_s) ? plainDuration(t.p90_s) : "·",
                  ],
                };
              })}
            />
          ) : failed ? (
            <NotLoaded />
          ) : (
            <Skeleton
              label="alerts by severity"
              rows={3}
              header
              className="rounded-none border-0"
            />
          )}
        </Card>
      </div>
    </div>
  );
}

/** A card whose read failed: the error with Retry is above the tiles, so no number here
 * and no loading bars that never end. */
function NotLoaded() {
  return <p className="px-3 py-2 text-sm text-text-muted">Could not load</p>;
}

/** An open count that opens the Queue with that filter; a zero stays plain. */
function CountLink({ n, to, what }: { n: number; to: string; what: string }) {
  if (n === 0) return <span className="text-text-muted">0</span>;
  return (
    <a
      href={`/alerts#${to}`}
      aria-label={`${n.toLocaleString()} open, ${what}. Open the Queue`}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        navigate("alerts", to);
      }}
      className="text-accent-text hover:underline"
    >
      {n.toLocaleString()}
    </a>
  );
}

interface CountTableProps {
  label: string;
  head: string[];
  rows: { key: string; name: ReactNode; cells: ReactNode[] }[];
}

function CountTable({ label, head, rows }: CountTableProps) {
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-text-secondary">
            {head.map((h, i) => (
              <th key={h} className={i ? "px-3 py-2 text-right" : "px-3 py-2"}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-b border-border last:border-0">
              <th scope="row" className="px-3 py-2 text-left font-normal">
                {r.name}
              </th>
              {r.cells.map((c, i) => (
                <td key={i} className="px-3 py-2 text-right font-mono tabular-nums">
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
