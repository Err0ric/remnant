import { useQuery } from "@tanstack/react-query";
import { EntityLink } from "@/components/EntityLink";
import { InlineError } from "@/components/InlineError";
import { Card } from "@/components/Card";
import { CardAction } from "@/components/CardAction";
import { SeverityMark } from "@/components/SeverityMark";
import { StateNotice } from "@/components/StateNotice";
import { Truncate } from "@/components/Truncate";
import { When } from "@/components/When";
import { RESTRICTED_NOTE } from "@/features/alerts/kinds";
import { api, type AlertItem, type AlertLines, type Overview, type Source } from "@/lib/api";
import { cn } from "@/lib/cn";
import { navigate, pathFor, type PageId } from "@/lib/route";
import { listOf, sourceStates } from "./Attention";

/** Alert rows shown after the blind rows; the rest are behind "View all", which opens Alerts. */
export const SHOWN = 5;

/** The order of ADR-0052 section 3.9: blind states, High alerts, other alerts, AI review. */
export type Order = 1 | 2 | 3 | 4;

export interface NeedsYouRow {
  key: string;
  order: Order;
  /** A blind row has no severity: it is not an alert. */
  severity: "high" | "medium" | null;
  kind: string;
  title: string;
  /** Who or what it is about, when the row names one. */
  subject:
    { kind: "user" | "host" | "ip"; value: string } | { kind: "source"; value: string } | null;
  at: string | null;
  page: PageId;
  tab?: string;
}

const TEMPLATE_MISSING = /is storing events without its parser: template (\S+) is not available/;

/** What a source's own problem is called, and said in a few words. */
function blindSource(
  id: string,
  problem: string,
  health: Overview["sources"][number] | undefined,
): Pick<NeedsYouRow, "kind" | "title"> {
  const missing = TEMPLATE_MISSING.exec(health?.error ?? "");
  if (missing)
    return {
      kind: "Template missing",
      title: `${id} is stored without its parser (template ${missing[1]})`,
    };
  if (problem === "has errors") return { kind: "Source error", title: `${id} has errors` };
  return { kind: "Source down", title: `${id} ${problem}` };
}

/** Whether an AI Watch alert is a review task, not something that fired. The server says
 * which lines are (it knows the review status); an answer without that list falls back to
 * the alert's own words. */
function isReview(i: AlertItem, review: string[] | undefined): boolean {
  if (review) return review.includes(i.item_id);
  return i.kind === "ai_watch" && /not reviewed/i.test(`${i.title} ${i.why ?? ""}`);
}

const KIND: Record<AlertItem["kind"], string> = {
  schedule: "Schedule",
  rule: "Rule",
  ai_watch: "AI Watch",
  gap: "Source gap",
};

/** Every row of the Needs you list, in its order: blind rows first (a source that is down
 * or in error, a missing template, detection that is paused), then High alerts, then other
 * alerts, then AI review items, newest first within each. A source gap alert is a blind row,
 * never a severity row: it means the viewer cannot see, not that something fired. */
export function needsYouRows(
  lines: (Pick<AlertLines, "items"> & Partial<Pick<AlertLines, "runs" | "review">>) | undefined,
  sources: Source[],
  overview: Overview | undefined,
): NeedsYouRow[] {
  const rows: NeedsYouRow[] = [];
  const health = new Map(
    listOf<Overview["sources"][number]>(overview?.sources).map((h) => [h.source_id, h]),
  );
  const items = listOf<AlertItem>(lines?.items);
  // A "gap" alert is not always about a source: a missed backup and undelivered hooks
  // records use the kind too. Only a gap on a source the viewer has can be a blind row.
  const known = new Set([...health.keys(), ...listOf<Source>(sources).map((x) => x.source_id)]);
  const onSource = (i: AlertItem) =>
    i.kind === "gap" &&
    (known.size
      ? known.has(i.subject)
      : // Nothing loaded to check against: a source id, and not the backup's own subject.
        /^[a-z0-9][a-z0-9_]{0,63}$/.test(i.subject) && i.subject !== "backup");
  const gapItem = new Map(items.filter(onSource).map((i) => [i.subject, i]));
  const said = new Set<string>();
  for (const s of sourceStates(sources, overview)) {
    if (!s.problem) continue;
    const h = health.get(s.id);
    const item = gapItem.get(s.id) ?? null;
    const alertId = item?.item_id ?? h?.gap_alert ?? null;
    said.add(s.id);
    rows.push({
      key: `source:${s.id}`,
      order: 1,
      severity: null,
      ...blindSource(s.id, s.problem, h),
      subject: { kind: "source", value: s.id },
      at: h?.quiet_since ?? item?.created_at ?? h?.last_event_at ?? null,
      // The open gap alert when there is one (close it there); otherwise the source on Health.
      page: alertId ? "alerts" : "health",
      tab: alertId ? `item=${alertId}` : `source=${encodeURIComponent(s.id)}`,
    });
  }
  // A gap alert on a source that has no problem row above. While the gap lasts it is still
  // a blind row. Once the source sends again the alert is only waiting to be closed: the
  // alert says so, or the Overview lists the source and sees nothing wrong with it now (its
  // condition may still be "gap" for a day, for the gap that ended). A source someone paused
  // is not sending on purpose. Both are ordinary alert rows below, never pinned as blind.
  const paused = (i: AlertItem) => health.get(i.subject)?.condition === "paused";
  const ended = (i: AlertItem) =>
    Boolean(i.resolved) || (health.has(i.subject) && !said.has(i.subject) && !paused(i));
  const lasting = (i: AlertItem) => !ended(i) && !paused(i);
  for (const i of gapItem.values())
    if (!said.has(i.subject) && lasting(i))
      rows.push({
        key: `gap:${i.item_id}`,
        order: 1,
        severity: null,
        kind: "Source down",
        title: i.title,
        subject: { kind: "source", value: i.subject },
        at: i.created_at,
        page: "alerts",
        tab: `item=${i.item_id}`,
      });
  // Detection the system paused (D236). A schedule someone paused themselves is their
  // choice, not a blind state, as a source someone paused is not.
  for (const p of listOf<Overview["paused"][number]>(overview?.paused).filter((x) => !x.by_person))
    rows.push({
      key: `paused:${p.schedule_id}`,
      order: 1,
      severity: null,
      kind: "Detection paused",
      title: p.reason ? `${p.name}: ${p.reason}` : p.name,
      subject: null,
      at: null,
      page: "schedules",
    });

  const seen = new Set<string>();
  for (const i of items) {
    // A source gap that still lasts is a blind row above (the source's own, or the alert's).
    if (onSource(i) && (said.has(i.subject) || lasting(i))) continue;
    const group = `${i.kind}:${i.subject}`;
    if (seen.has(group)) continue; // one row per kind and subject, the newest
    seen.add(group);
    const review = isReview(i, lines?.review);
    const runs = lines?.runs?.[i.item_id] ?? 1;
    const reason = i.why ?? "";
    // The reason is left out when the title already says it, or when it is only the review
    // status an AI Watch title names ("New AI service: X" is about a service not approved).
    const saidIt =
      !reason ||
      review ||
      (i.kind === "ai_watch" && /^(not reviewed yet|not approved)$/i.test(reason)) ||
      i.title.toLowerCase().includes(reason.toLowerCase());
    const what = saidIt ? i.title : `${i.title}: ${reason}`;
    const title = onSource(i) && ended(i) ? `${what}: sending again, close the alert` : what;
    // "<source>/<machine>": records a collector on that machine did not deliver.
    const collector = i.kind === "gap" && i.subject.includes("/");
    const person = i.people?.[0];
    const device = i.devices?.[0];
    rows.push({
      key: `alert:${i.item_id}`,
      order: review ? 4 : i.severity === "high" ? 2 : 3,
      severity: i.severity,
      kind: review
        ? "AI review"
        : i.kind !== "gap" || onSource(i)
          ? KIND[i.kind]
          : collector
            ? "Collector"
            : i.subject === "backup"
              ? "Backup"
              : "Health",
      title: runs > 1 ? `${title} (${runs} runs)` : title,
      subject:
        i.kind === "gap"
          ? onSource(i)
            ? { kind: "source", value: i.subject }
            : collector && known.has(i.subject.split("/")[0] ?? "")
              ? { kind: "source", value: i.subject.split("/")[0] ?? "" }
              : null
          : person
            ? { kind: "user", value: person }
            : device
              ? // A device may be known only by its address.
                { kind: /^[\d.]+$|:/.test(device) ? "ip" : "host", value: device }
              : null,
      at: i.created_at,
      // A review item is decided on AI usage; everything else on its alert.
      page: review ? "ai" : "alerts",
      tab: review ? "inventory" : `item=${i.item_id}`,
    });
  }
  return rows.sort(
    (a, b) =>
      a.order - b.order || (b.at ?? "").localeCompare(a.at ?? "") || a.key.localeCompare(b.key),
  );
}

/** Blind rows are all shown; alert and review rows up to `SHOWN`. */
export function shownRows(rows: NeedsYouRow[]): NeedsYouRow[] {
  const blind = rows.filter((r) => r.order === 1);
  return [...blind, ...rows.filter((r) => r.order !== 1).slice(0, SHOWN)];
}

/** Who or what a row is about: a source opens Health, anyone else their page. At most
 * 220px wide; `w-max` makes the column take the value's width up to that. */
function Subject({ subject }: { subject: NeedsYouRow["subject"] }) {
  if (!subject) return null;
  // Inline: a row copies as one line of cells.
  const box = "inline-block w-max max-w-55 align-bottom font-mono text-data";
  if (subject.kind !== "source")
    return <EntityLink kind={subject.kind} value={subject.value} className={box} />;
  const tab = `source=${encodeURIComponent(subject.value)}`;
  return (
    <a
      href={`${pathFor("health")}#${tab}`}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        navigate("health", tab);
      }}
      title={subject.value}
      aria-label={subject.value}
      className={cn("group text-accent-text hover:underline", box)}
    >
      <Truncate value={subject.value} kind="name" inLink className="group-hover:underline" />
    </a>
  );
}

const href = (r: NeedsYouRow) => `${pathFor(r.page)}${r.tab ? `#${r.tab}` : ""}`;

/** The one list of what needs the viewer (ADR-0052 section 3.9, DESIGN.md 6.3). A blind
 * state is said once, here, and on Health: there is no Health banner and no Sources line.
 * Hidden entirely when nothing needs anyone. */
export function NeedsYou() {
  // Only the lines shown (owner, 2026-11-11: the audit log records access, not page loads).
  const alerts = useQuery({
    queryKey: ["alerts", "lines", SHOWN, "severity"],
    queryFn: () => api.alertLines(SHOWN),
  });
  const sources = useQuery({ queryKey: ["source-list"], queryFn: api.sources });
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 60_000,
  });
  const failed = [alerts, sources, overview].filter((q) => q.isError && !q.data);
  if (failed.length)
    return (
      <section aria-label="Needs you" className="rounded-card border border-border bg-surface">
        <InlineError
          what="Needs you"
          error={failed[0]?.error}
          onRetry={() => failed.forEach((q) => void q.refetch())}
          retrying={failed.some((q) => q.isFetching)}
        />
      </section>
    );
  const rows = needsYouRows(alerts.data, sources.data ?? [], overview.data);
  const restricted = alerts.data?.restricted === true;
  const shown = shownRows(rows);
  // Alert lines the server counted but did not send, and rows past the cap. A gap alert
  // that was not sent but whose source already has its blind row here is not one more.
  const items = listOf<AlertItem>(alerts.data?.items);
  const sentGaps = new Set(items.filter((i) => i.kind === "gap").map((i) => i.subject));
  const blindSources = new Set(
    rows.flatMap((r) => (r.order === 1 && r.subject?.kind === "source" ? [r.subject.value] : [])),
  );
  const saidAbove = listOf<string>(alerts.data?.gap_sources).filter(
    (id) => blindSources.has(id) && !sentGaps.has(id),
  ).length;
  const unsent = Math.max(0, (alerts.data?.groups ?? items.length) - items.length - saidAbove);
  const more = rows.length - shown.length + unsent;
  if (!rows.length && !more && !restricted) return null;
  const count = rows.length + unsent;
  return (
    <Card
      title="Needs you"
      note={count ? <span className="tabular-nums text-text-secondary">{count}</span> : undefined}
      action={
        more > 0 ? (
          <CardAction
            onClick={() => navigate("alerts")}
            title={`${more.toLocaleString()} more on Alerts`}
          >
            View all
          </CardAction>
        ) : undefined
      }
    >
      {shown.length ? (
        // Badge, kind, subject, title, time (D257): kind and subject take their content (the
        // subject at most 220px, cut by `Truncate`), the title the rest of the row in two lines.
        <table className="w-full text-base">
          <thead className="sr-only">
            <tr>
              <th>Severity</th>
              <th className="max-md:hidden">Kind</th>
              <th className="max-lg:hidden">Who or what</th>
              <th>What</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const blind = r.order === 1;
              return (
                <tr
                  key={r.key}
                  data-needs-you={blind ? "blind" : "alert"}
                  className={cn("border-t border-border first:border-t-0", blind && "bg-warn-tint")}
                >
                  <td
                    className={cn(
                      "w-px whitespace-nowrap py-1.5 pl-3 pr-3 align-middle",
                      // The bar is a shape, so a blind row never reads as an alert row.
                      blind && "border-l-2 border-l-warn pl-2.5",
                    )}
                  >
                    {blind ? (
                      <span className="rounded-badge border border-warn px-1.5 text-xs font-semibold text-warn">
                        Blind
                      </span>
                    ) : r.severity ? (
                      <SeverityMark
                        tone={r.severity}
                        label={r.severity === "high" ? "High" : "Medium"}
                      />
                    ) : (
                      <span className="text-text-muted">·</span>
                    )}
                  </td>
                  <td className="w-px whitespace-nowrap py-1.5 pr-4 text-text-secondary max-md:hidden">
                    {r.kind}
                  </td>
                  <td className="w-px py-1.5 pr-4 max-lg:hidden">
                    <Subject subject={r.subject} />
                  </td>
                  <td className="py-1.5 pr-4">
                    <a
                      href={href(r)}
                      onClick={(e) => {
                        if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                        e.preventDefault();
                        navigate(r.page, r.tab);
                      }}
                      data-needs-you-title=""
                      className="line-clamp-2 text-text [overflow-wrap:anywhere] hover:underline"
                      title={r.title}
                    >
                      <span className="md:hidden">{r.kind}: </span>
                      {r.title}
                    </a>
                  </td>
                  <td className="w-px whitespace-nowrap py-1.5 pr-3 text-right align-middle">
                    {r.at ? <When iso={r.at} className="text-text-muted" /> : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}
      {restricted ? (
        <div className={cn("p-2", shown.length > 0 && "border-t border-border")}>
          <StateNotice>{RESTRICTED_NOTE}</StateNotice>
        </div>
      ) : null}
    </Card>
  );
}
