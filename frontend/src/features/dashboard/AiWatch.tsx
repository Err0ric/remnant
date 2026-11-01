import { useQuery } from "@tanstack/react-query";
import {
  api,
  type AiStatus,
  type AiWatchCard,
  type AiWatchDay,
  type AiWatchSummary,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { navigate, pathFor } from "@/lib/route";
import { openDrill } from "@/lib/drill";
import { EntityLink } from "@/components/EntityLink";
import { PeoplePending } from "@/components/PeoplePending";
import { LoadFailed } from "@/components/LoadFailed";
import { When } from "@/components/When";
import { StatusBadge, STATUS_LABEL } from "@/features/ai/StatusBadge";
import { TrendChart, TrendLegend } from "./TrendChart";
import { compareLine, NoHistory } from "./History";

const ORDER: AiStatus[] = ["not_approved", "unreviewed", "approved"];

/** "+1 vs previous 7 days", "same as previous 7 days". */
export function delta(card: AiWatchCard, days: number): string {
  if (card.value === null || card.previous === null) return "";
  const d = card.value - card.previous;
  const span = days === 1 ? "previous 24 hours" : `previous ${days} days`;
  return d === 0 ? `same as ${span}` : `${d > 0 ? "+" : ""}${d} vs ${span}`;
}

/** What each card counts, for its (i) (ADR-0038 row 13). */
const ABOUT: Record<AiWatchCard["key"], string> = {
  services: "AI services in use that are not approved or not reviewed yet, in this range.",
  people:
    "People using those services. Devices with no person matched are counted apart, never added in.",
  agents: "AI agents and MCP servers first seen in this range.",
  consent:
    "Microsoft 365 app consents granted in this range, Graph and the Management API counted once. Blocked attempts are shown apart.",
  sensitive: "Sensitive data signals Claude Code telemetry reported (keys, tokens, card numbers).",
};

/** The change against the previous period as a neutral pill: an arrow and the number.
 * Never green or red: more AI use is not good or bad by itself (ADR-0038 row 13). */
function DeltaPill({
  card,
  days,
  onOpen,
}: {
  card: AiWatchCard;
  days: number;
  onOpen?: () => void;
}) {
  if (card.value === null || card.previous === null) return null;
  const d = card.value - card.previous;
  const cls =
    "rounded-badge bg-surface-head px-1.5 font-mono text-xs font-semibold tabular-nums text-text";
  const body = (
    <>
      <span aria-hidden="true">
        {d === 0 ? "same" : `${d > 0 ? "↑" : "↓"} ${Math.abs(d).toLocaleString()}`}
      </span>
      <span className="sr-only">{delta(card, days)}</span>
    </>
  );
  if (!onOpen)
    return (
      <span className={cls} title={delta(card, days)}>
        {body}
      </span>
    );
  return (
    <button
      type="button"
      data-drill=""
      onClick={onOpen}
      title={`${delta(card, days)}. Open the period before in Search`}
      className={cn(cls, "cursor-pointer hover:bg-border")}
    >
      {body}
    </button>
  );
}

/** AI Watch (ADR-0035 Part 2): is anyone using AI we have not approved? Five cards, AI use
 * over 30 days by review status, and the top services, on the viewer's own sources.
 * Hidden on an install with no AI use and nothing to count. */
export function AiWatch({ days = 7 }: { days?: number }) {
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 60_000,
  });
  const q = useQuery({
    queryKey: ["ai-watch", days],
    queryFn: () => api.aiWatchSummary(days),
    refetchInterval: 300_000,
  });
  if (q.isLoading)
    return <div aria-busy="true" className="h-48 animate-pulse rounded-card bg-surface" />;
  if (q.isError && !q.data)
    return (
      <section aria-label="AI Watch" className="rounded-card border border-border bg-surface">
        <h2 className="border-b border-border px-3 py-2 text-base font-semibold">AI Watch</h2>
        <LoadFailed
          what="AI Watch"
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
        />
      </section>
    );
  const s = q.data;
  if (!s) return null;
  const used = s.chart.some((d) => d.approved + d.unreviewed + d.not_approved > 0);
  if (!used && !s.cards.some((c) => (c.value ?? 0) > 0)) return null;
  const shown = s.cards.filter((c) => !c.needs);
  // The newest event of the sources AI Watch read: the chart shades the days after it.
  const lasts = (overview.data?.sources ?? [])
    .filter((x) => s.sources.includes(x.source_id) && x.last_event_at)
    .map((x) => x.last_event_at as string);
  const dataUntil = lasts.length ? (lasts.sort().slice(-1)[0] ?? null) : null;
  const missing = s.cards.filter((c) => c.needs);
  return (
    <section aria-label="AI Watch" className="rounded-card border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-3 py-2">
        <h2 className="text-base font-semibold">AI Watch</h2>
        <span className="text-sm text-text-muted">
          {compareLine(
            s.compared ?? true,
            s.since ?? null,
            days === 1 ? "the previous 24 hours" : `the previous ${days} days`,
          )}
        </span>
        <button
          type="button"
          onClick={() => navigate("ai", "services")}
          className="ml-auto text-sm text-accent-text hover:underline"
        >
          Open AI usage
        </button>
      </div>
      {s.people_pending_days ? (
        <div className="border-b border-border px-3 py-1.5">
          <PeoplePending pending={s.people_pending_days} of={s.people_days} />
        </div>
      ) : null}
      {/* Cards whose source is not set up take no card (F62): one muted line instead. All
          shown cards in one row from 1024 px; two across below, an odd last one spanning. */}
      <div
        className={cn("grid grid-cols-2 gap-px bg-border", COLS[shown.length] ?? "lg:grid-cols-5")}
      >
        {shown.map((c) => (
          <Card
            key={c.key}
            card={c}
            days={s.days}
            odd={shown.length % 2 === 1}
            history={{ compared: s.compared ?? true, since: s.since ?? null }}
            bounds={{ start: s.start, end: s.end, before: s.before ?? s.start }}
          />
        ))}
      </div>
      {missing.length ? <NotSetUp cards={missing} /> : null}
      <NewList items={s.new} />
      <div className="grid min-w-0 gap-4 border-t border-border p-3 lg:grid-cols-[2fr_3fr]">
        {/* The rollup is daily: with the 24 hour window the chart shows the last 7 days. */}
        <Chart
          chart={s.chart}
          days={Math.max(7, s.days)}
          dataUntil={dataUntil}
          onOpenDay={
            s.chart_drill
              ? (day) => {
                  const from = `${day}T00:00:00Z`;
                  const to = new Date(Date.parse(from) + 86_400_000).toISOString();
                  opener(s.chart_drill, `AI use, ${dayLabel(day)}`, {
                    start: from,
                    end: to,
                    before: from,
                  })?.();
                }
              : undefined
          }
        />
        <Top summary={s} />
      </div>
    </section>
  );
}

const COLS: Record<number, string> = {
  1: "lg:grid-cols-1",
  2: "lg:grid-cols-2",
  3: "lg:grid-cols-3",
  4: "lg:grid-cols-4",
  5: "lg:grid-cols-5",
};

/** A card label inside a sentence: the first letter lowered unless it starts a word in
 * capitals, so "MCP servers" and "AI" keep theirs ("new agents and MCP servers"). */
export function midSentence(label: string): string {
  const [a, b] = [label[0] ?? "", label[1] ?? ""];
  return b && b === b.toUpperCase() && b !== b.toLowerCase()
    ? label
    : a.toLowerCase() + label.slice(1);
}

/** "Not set up: App consent grants (needs a Microsoft 365 source)" with the setup link. */
function NotSetUp({ cards }: { cards: AiWatchCard[] }) {
  const byNeed = new Map<string, string[]>();
  for (const c of cards) byNeed.set(c.needs ?? "", [...(byNeed.get(c.needs ?? "") ?? []), c.label]);
  return (
    <p className="border-t border-border px-3 py-1.5 text-sm text-text-muted">
      Not set up:{" "}
      {[...byNeed].map(([need, labels], i) => (
        <span key={need}>
          {i ? "; " : ""}
          {labels.map(midSentence).join(", ")} (needs {need})
        </span>
      ))}
      .{" "}
      <button
        type="button"
        onClick={() => navigate("sources")}
        className="text-accent-text hover:underline"
      >
        Add a source
      </button>
    </p>
  );
}

const NEW_KIND = { service: "AI service", mcp: "MCP server", agent: "agent" } as const;

/** New in 24 hours (F62): first seen in the data, never from a review decision (D116). */
function NewList({ items }: { items: AiWatchSummary["new"] }) {
  return (
    <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5 border-t border-border px-3 py-1.5 text-sm">
      <span className="font-semibold">New in 24 hours</span>
      {items.length === 0 ? (
        <span className="text-text-muted">nothing first seen</span>
      ) : (
        <>
          {items.slice(0, 6).map((n) =>
            n.item_id ? (
              <a
                key={`${n.kind}:${n.id}`}
                href={`${pathFor("alerts")}#item=${n.item_id}`}
                onClick={(e) => {
                  if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                  e.preventDefault();
                  navigate("alerts", `item=${n.item_id}`);
                }}
                title={`First seen ${n.first_seen}`}
                className="min-w-0 text-accent-text hover:underline"
              >
                {n.name} <span className="text-text-muted">({NEW_KIND[n.kind]})</span>
              </a>
            ) : (
              <span key={`${n.kind}:${n.id}`} title={`First seen ${n.first_seen}`}>
                {n.name} <span className="text-text-muted">({NEW_KIND[n.kind]})</span>
              </span>
            ),
          )}
          {items.length > 6 ? (
            <span className="text-text-muted">and {items.length - 6} more</span>
          ) : null}
        </>
      )}
    </div>
  );
}

interface Bounds {
  start: string;
  end: string;
  before: string;
}

/** Opens a number's rows in Search over the period, or the period before (ADR-0039). */
function opener(sql: string | null | undefined, label: string, b: Bounds, before = false) {
  if (!sql) return undefined;
  return () =>
    openDrill({
      sql,
      from: before ? b.before : b.start,
      to: before ? b.start : b.end,
      origin: `Dashboard > AI Watch > ${label}`,
    });
}

interface CardProps {
  card: AiWatchCard;
  days: number;
  odd: boolean;
  history: { compared: boolean; since: string | null };
  bounds: Bounds;
}

function Card({ card, days, odd, history, bounds }: CardProps) {
  const partial = !history.compared && card.value !== null && card.previous !== null;
  // New agents and MCP servers are review items, not events: they open the queue.
  const link =
    opener(card.drill, card.label, bounds) ??
    (card.key === "agents" ? () => navigate("alerts", "review") : undefined);
  const before = days === 1 ? "the previous 24 hours" : `the previous ${days} days`;
  const openBefore =
    card.key === "agents"
      ? () => navigate("alerts", "review")
      : opener(card.drill_before ?? card.drill, `${card.label} (${before})`, bounds, true);
  const noun =
    card.key === "services"
      ? "services"
      : card.key === "people"
        ? "people"
        : card.key === "consent"
          ? "consents"
          : card.key === "agents"
            ? "review items"
            : "events";
  return (
    <div
      data-kpi={card.label}
      className={cn(
        "flex min-w-0 flex-col gap-0.5 bg-surface px-3 py-2.5",
        odd && "last:col-span-2 lg:last:col-span-1",
      )}
    >
      <span className="flex min-w-0 items-center gap-1.5 text-sm text-text-secondary">
        <span className="truncate" title={card.label}>
          {card.label}
        </span>
        <span
          role="img"
          aria-label={`About ${midSentence(card.label)}: ${ABOUT[card.key]}`}
          title={ABOUT[card.key]}
          className="flex size-3.5 shrink-0 cursor-help items-center justify-center rounded-full border border-text-muted text-[10px] font-semibold leading-none text-text-muted"
        >
          i
        </span>
      </span>
      {card.needs ? (
        <span className="text-sm text-text-muted">
          Needs{" "}
          <button
            type="button"
            onClick={() => navigate("sources")}
            className="text-accent-text hover:underline"
          >
            {card.needs}
          </button>
        </span>
      ) : card.restricted ? (
        <span className="text-sm text-text-muted">Restricted</span>
      ) : (
        <>
          <span className="flex flex-wrap items-center gap-x-2">
            {link ? (
              <button
                type="button"
                data-drill=""
                onClick={link}
                title={
                  card.key === "agents"
                    ? "Open the review queue"
                    : `Open ${(card.value ?? 0).toLocaleString()} ${noun} in Search`
                }
                className={cn(
                  "self-start text-kpi tabular-nums underline-offset-4 hover:underline min-[1500px]:text-kpi-lg",
                  card.value === 0 && !card.devices ? "text-ok" : "text-text",
                )}
              >
                {(card.value ?? 0).toLocaleString()}
              </button>
            ) : (
              <span
                className={cn(
                  "text-kpi tabular-nums min-[1500px]:text-kpi-lg",
                  card.value === 0 && !card.devices ? "text-ok" : "text-text",
                )}
              >
                {(card.value ?? 0).toLocaleString()}
              </span>
            )}
            {partial ? null : <DeltaPill card={card} days={days} onOpen={openBefore} />}
          </span>
          {partial ? <NoHistory since={history.since} before={before} /> : null}
          {card.devices ? (
            <button
              type="button"
              data-drill=""
              onClick={
                opener(card.devices_drill, "Devices not matched to a person", bounds) ??
                (() => navigate("ai", "services"))
              }
              title="Open these devices in Search"
              className="self-start text-left text-sm text-accent-text hover:underline"
            >
              {card.devices.toLocaleString()} {card.value ? "more " : ""}
              {card.devices === 1 ? "device" : "devices"} not matched to a person
            </button>
          ) : null}
          {/* Two lines, then the full text on hover (owner edit 6). */}
          <span className="line-clamp-2 text-sm text-text-muted" title={card.context}>
            {card.context}
          </span>
          {card.unreviewed ? (
            <a
              href={`${pathFor("alerts")}#review`}
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                e.preventDefault();
                navigate("alerts", "review");
              }}
              className="self-start text-sm text-accent-text no-underline hover:underline"
            >
              {card.unreviewed.toLocaleString()} not reviewed
            </a>
          ) : null}
          {card.blocked ? (
            <>
              <button
                type="button"
                data-drill=""
                onClick={opener(card.blocked_drill, "Blocked consent attempts", bounds)}
                title="Open the blocked attempts in Search"
                className="self-start text-left text-sm text-accent-text hover:underline"
              >
                {card.blocked.toLocaleString()} blocked consent{" "}
                {card.blocked === 1 ? "attempt" : "attempts"}
              </button>
              <span className="line-clamp-2 text-sm text-text-muted" title={card.blocked_context}>
                {card.blocked_context}
              </span>
            </>
          ) : null}
        </>
      )}
    </div>
  );
}

const dayLabel = (iso: string) =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });

/** Stack order, bottom first (owner 2026-10-30): approved, unreviewed, not approved. */
const STACK: AiStatus[] = ["approved", "unreviewed", "not_approved"];
const COLOR: Record<AiStatus, string> = {
  approved: "local-text",
  unreviewed: "text-muted",
  not_approved: "sev-critical-text",
};

interface ChartProps {
  chart: AiWatchDay[];
  /** The block's window (7 or 30 days): the chart shows the same days as the cards. */
  days?: number;
  /** The newest event of the sources AI Watch reads: days after it have no data. */
  dataUntil?: string | null;
  /** Opens one day's AI use in Search (ADR-0039). */
  onOpenDay?: (day: string) => void;
}

/** AI use per day by review status as a stacked area (ADR-0038 rows 11, 15; owner
 * 2026-10-30), values on hover, and a hatched band over days after the data stops. */
export function Chart({ chart: all, days = 30, dataUntil = null, onOpenDay }: ChartProps) {
  const total = (d: AiWatchDay) => d.approved + d.unreviewed + d.not_approved;
  const windowed = all.slice(-days);
  // Until there is a full window of data, the chart covers the days that exist (F62,
  // owner 2026-10-29): "AI use since Oct 22", never a line squeezed into a corner.
  const first = windowed.findIndex((d) => total(d) > 0);
  const chart = first > 0 ? windowed.slice(first) : windowed;
  const sums = Object.fromEntries(
    ORDER.map((st) => [st, chart.reduce((n, d) => n + d[st], 0)]),
  ) as Record<AiStatus, number>;
  const summary = ORDER.map((st) => `${STATUS_LABEL[st]} ${sums[st].toLocaleString()}`).join(", ");
  const lastDay = dataUntil ? dataUntil.slice(0, 10) : null;
  const stopped = lastDay && chart.some((d) => d.day > lastDay) ? lastDay : null;
  const lastWithData = stopped ? chart.filter((d) => d.day <= stopped).length - 1 : undefined;
  return (
    <TrendChart
      title={
        chart.length < windowed.length
          ? `AI use since ${dayLabel(chart[0]?.day ?? "")}`
          : `AI use, last ${days} days`
      }
      note={`events per day${stopped ? `; no data after ${dayLabel(stopped)}` : ""}`}
      stacked
      series={STACK.map((st) => ({
        key: st,
        label: STATUS_LABEL[st],
        values: chart.map((d) => d[st]),
        color: COLOR[st],
      }))}
      lastWithData={lastWithData}
      partial={stopped ? undefined : "so far"}
      onOpen={onOpenDay ? (i) => chart[i] && onOpenDay(chart[i].day) : undefined}
      pointLabel={(i) => dayLabel(chart[i]?.day ?? "")}
      axisLabel={(i) => dayLabel(chart[i]?.day ?? "")}
      summary={`AI use per day over ${chart.length} days by review status: ${summary}${
        stopped ? `. No data after ${dayLabel(stopped)}` : ""
      }`}
      legend={
        <TrendLegend
          items={[...STACK].reverse().map((st) => ({
            label: (
              <>
                {STATUS_LABEL[st]}{" "}
                <span className="font-mono tabular-nums">{sums[st].toLocaleString()}</span>
              </>
            ),
            color: COLOR[st],
          }))}
        />
      }
    />
  );
}

function Top({ summary }: { summary: AiWatchSummary }) {
  return (
    <div className="min-w-0">
      <div className="mb-2 flex items-baseline gap-2">
        <h3 className="text-sm font-semibold">Top services</h3>
        <span className="text-sm text-text-muted">last {summary.days} days</span>
        <button
          type="button"
          onClick={() => navigate("ai", "services")}
          className="ml-auto text-sm text-accent-text hover:underline"
        >
          View all
        </button>
      </div>
      {summary.top.length === 0 ? (
        <p className="text-sm text-text-secondary">No AI use in this range.</p>
      ) : (
        <div className="overflow-x-auto">
          <table aria-label="Top AI services" className="w-full text-sm">
            <thead>
              <tr className="text-left text-text-muted">
                <th className="py-1 pr-3 font-normal">Service</th>
                <th className="py-1 pr-3 font-normal">Status</th>
                <th className="py-1 pr-3 text-right font-normal">People</th>
                <th className="py-1 pr-3 text-right font-normal">Devices</th>
                <th className="hidden py-1 pr-3 font-normal 2xl:table-cell">First seen</th>
                <th className="py-1 font-normal">Last seen</th>
              </tr>
            </thead>
            <tbody>
              {summary.top.map((t) => (
                <tr key={t.service_id} className="border-t border-border">
                  <td className="py-1 pr-3">
                    <EntityLink kind="service" value={t.service_id} label={t.name} />
                  </td>
                  <td className="py-1 pr-3">
                    <StatusBadge status={t.status} />
                  </td>
                  <td
                    className="py-1 pr-3 text-right font-mono tabular-nums"
                    title={t.people ? undefined : "No person named in these events; see Devices"}
                  >
                    {t.people || "·"}
                  </td>
                  <td className="py-1 pr-3 text-right font-mono tabular-nums">{t.machines}</td>
                  <td className="hidden whitespace-nowrap py-1 pr-3 2xl:table-cell">
                    <When iso={t.first_seen} className="text-text-secondary" />
                  </td>
                  <td className="whitespace-nowrap py-1">
                    <When iso={t.last_seen} className="text-text-secondary" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
