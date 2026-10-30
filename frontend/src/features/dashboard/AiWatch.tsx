import { useState } from "react";
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
import { seedSearch } from "@/lib/searchSeed";
import { EntityLink } from "@/components/EntityLink";
import { PeoplePending } from "@/components/PeoplePending";
import { LoadFailed } from "@/components/LoadFailed";
import { When } from "@/components/When";
import { StatusBadge, STATUS_LABEL } from "@/features/ai/StatusBadge";

/** Bar fills per review status: the same meaning as the status badges, at most 3 colors
 * (ADR-0035 owner note: parts of a whole). */
const FILL: Record<AiStatus, string> = {
  not_approved: "bg-sev-critical-text",
  unreviewed: "bg-text-muted",
  approved: "bg-local-text",
};
const ORDER: AiStatus[] = ["not_approved", "unreviewed", "approved"];
const RANGES = [7, 30] as const;

/** "+1 vs previous 7 days", "same as previous 7 days". */
export function delta(card: AiWatchCard, days: number): string {
  if (card.value === null || card.previous === null) return "";
  const d = card.value - card.previous;
  const span = `previous ${days} ${days === 1 ? "day" : "days"}`;
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
function DeltaPill({ card, days }: { card: AiWatchCard; days: number }) {
  if (card.value === null || card.previous === null) return null;
  const d = card.value - card.previous;
  return (
    <span
      className="flex items-center gap-1.5 text-sm text-text-secondary"
      title={delta(card, days)}
    >
      <span className="rounded-badge bg-surface-head px-1.5 font-mono text-xs font-semibold tabular-nums text-text">
        {d === 0 ? "same" : `${d > 0 ? "↑" : "↓"} ${Math.abs(d).toLocaleString()}`}
      </span>
      <span className="sr-only">{delta(card, days)}</span>
      <span aria-hidden="true">vs previous {days} days</span>
    </span>
  );
}

/** AI Watch (ADR-0035 Part 2): is anyone using AI we have not approved? Five cards, AI use
 * over 30 days by review status, and the top services, on the viewer's own sources.
 * Hidden on an install with no AI use and nothing to count. */
export function AiWatch() {
  const [days, setDays] = useState<(typeof RANGES)[number]>(7);
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
        <div role="group" aria-label="Range" className="flex text-sm">
          {RANGES.map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={days === d}
              onClick={() => setDays(d)}
              className={cn(
                "rounded px-2 py-0.5",
                days === d
                  ? "bg-surface-head font-semibold text-text"
                  : "text-text-secondary hover:text-text",
              )}
            >
              {d} days
            </button>
          ))}
        </div>
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
          <Card key={c.key} card={c} days={s.days} odd={shown.length % 2 === 1} />
        ))}
      </div>
      {missing.length ? <NotSetUp cards={missing} /> : null}
      <NewList items={s.new} />
      <div className="grid min-w-0 gap-4 border-t border-border p-3 lg:grid-cols-[2fr_3fr]">
        <Chart chart={s.chart} days={s.days} dataUntil={dataUntil} />
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

/** Opens the rows behind a card in Search. */
function openRows(sql: string) {
  seedSearch({ sql, range: "30d" });
  navigate("search");
}

function Card({ card, days, odd }: { card: AiWatchCard; days: number; odd: boolean }) {
  const rowsSql = card.rows_sql;
  const blockedSql = card.blocked_sql;
  const link = rowsSql
    ? () => openRows(rowsSql)
    : card.key === "agents"
      ? () => navigate("alerts")
      : card.key === "services" || card.key === "people"
        ? () => navigate("ai", "services")
        : card.key === "sensitive"
          ? () => navigate("ai", "people")
          : undefined;
  return (
    <div
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
          {link ? (
            <button
              type="button"
              onClick={link}
              className={cn(
                "self-start text-kpi tabular-nums hover:underline",
                card.value === 0 && !card.devices ? "text-ok" : "text-text",
              )}
            >
              {(card.value ?? 0).toLocaleString()}
            </button>
          ) : (
            <span
              className={cn(
                "text-kpi tabular-nums",
                card.value === 0 && !card.devices ? "text-ok" : "text-text",
              )}
            >
              {(card.value ?? 0).toLocaleString()}
            </span>
          )}
          {card.devices ? (
            <button
              type="button"
              onClick={() => navigate("ai", "services")}
              className="self-start text-left text-sm text-accent-text hover:underline"
            >
              {card.devices.toLocaleString()} {card.value ? "more " : ""}
              {card.devices === 1 ? "device" : "devices"} not matched to a person
            </button>
          ) : null}
          <DeltaPill card={card} days={days} />
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
                onClick={() => (blockedSql ? openRows(blockedSql) : undefined)}
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

/** Round a chart's top up to 1, 2, or 5 times a power of ten, so ticks read easily. */
function niceTop(n: number): number {
  const p = 10 ** Math.floor(Math.log10(Math.max(1, n)));
  return ([1, 2, 5, 10].find((m) => m * p >= n) ?? 10) * p;
}

const dayLabel = (iso: string) =>
  new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });

interface ChartProps {
  chart: AiWatchDay[];
  /** The block's window (7 or 30 days): the chart shows the same days as the cards. */
  days?: number;
  /** The newest event of the sources AI Watch reads: days after it have no data. */
  dataUntil?: string | null;
}

/** AI use per day by review status, in the block's window (ADR-0038 rows 11, 15): a y axis
 * with three ticks, dated x labels, totals printed over 7 bars or fewer, and a thin
 * hatched band over days after the data stops, so the bars before it stay readable. */
export function Chart({ chart: all, days = 30, dataUntil = null }: ChartProps) {
  const total = (d: AiWatchDay) => d.approved + d.unreviewed + d.not_approved;
  const windowed = all.slice(-days);
  // Until there is a full window of data, the chart covers the days that exist (F62,
  // owner 2026-10-29): "AI use since Oct 22", never bars squeezed into a corner.
  const first = windowed.findIndex((d) => total(d) > 0);
  const chart = first > 0 ? windowed.slice(first) : windowed;
  const top = niceTop(Math.max(2, ...chart.map(total))); // at least 2: whole-number ticks
  const sums = Object.fromEntries(
    ORDER.map((st) => [st, chart.reduce((n, d) => n + d[st], 0)]),
  ) as Record<AiStatus, number>;
  const summary = ORDER.map((st) => `${STATUS_LABEL[st]} ${sums[st].toLocaleString()}`).join(", ");
  const lastDay = dataUntil ? dataUntil.slice(0, 10) : null;
  const stopped = lastDay && chart.some((d) => d.day > lastDay) ? lastDay : null;
  const printed = chart.length <= 7;
  const mid = chart[Math.floor((chart.length - 1) / 2)];
  return (
    <figure className="min-w-0">
      <figcaption className="mb-2 text-sm font-semibold">
        {chart.length < windowed.length
          ? `AI use since ${dayLabel(chart[0]?.day ?? "")}`
          : `AI use, last ${days} days`}{" "}
        <span className="font-normal text-text-muted">
          events per day{stopped ? `; no data after ${dayLabel(stopped)}` : ""}
        </span>
      </figcaption>
      <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2">
        <div
          aria-hidden="true"
          className="flex h-28 flex-col justify-between text-right font-mono text-xs tabular-nums text-text-muted"
        >
          <span className="-mt-1.5">{top.toLocaleString()}</span>
          <span>{(top / 2).toLocaleString()}</span>
          <span className="-mb-1.5">0</span>
        </div>
        <div
          role="img"
          aria-label={`AI use per day over ${chart.length} days by review status: ${summary}${
            stopped ? `. No data after ${dayLabel(stopped)}` : ""
          }`}
          className="relative flex h-28 items-end gap-px border-b border-l border-border"
        >
          <div
            aria-hidden="true"
            className="absolute inset-x-0 top-0 border-t border-dashed border-border"
          />
          <div
            aria-hidden="true"
            className="absolute inset-x-0 top-1/2 border-t border-dashed border-border"
          />
          {chart.map((d) => {
            const none = stopped !== null && d.day > stopped;
            return (
              <div
                key={d.day}
                title={
                  none
                    ? `${dayLabel(d.day)}: no data`
                    : `${dayLabel(d.day)}: ${ORDER.map((st) => `${STATUS_LABEL[st]} ${d[st].toLocaleString()}`).join(", ")}`
                }
                className="relative flex h-full min-w-0 flex-1 flex-col justify-end"
                style={
                  none
                    ? {
                        backgroundImage:
                          "repeating-linear-gradient(135deg, var(--border) 0 1px, transparent 1px 6px)",
                      }
                    : undefined
                }
              >
                {printed && !none ? (
                  <span
                    className="absolute inset-x-0 text-center font-mono text-xs tabular-nums text-text-secondary"
                    style={{ bottom: `calc(${(total(d) / top) * 100}% + 2px)` }}
                  >
                    {total(d).toLocaleString()}
                  </span>
                ) : null}
                {ORDER.map((st) =>
                  d[st] ? (
                    <div
                      key={st}
                      className={FILL[st]}
                      style={{ height: `${Math.max(2, (d[st] / top) * 100)}%` }}
                    />
                  ) : null,
                )}
              </div>
            );
          })}
        </div>
        <span />
        <div className="mt-1 flex justify-between font-mono text-xs tabular-nums text-text-muted">
          <span>{dayLabel(chart[0]?.day ?? "")}</span>
          {chart.length > 2 && mid ? <span>{dayLabel(mid.day)}</span> : null}
          <span>{dayLabel(chart[chart.length - 1]?.day ?? "")}</span>
        </div>
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-text-secondary">
        {ORDER.map((st) => (
          <li key={st} className="flex items-center gap-1.5">
            <span aria-hidden="true" className={cn("inline-block size-2.5 rounded-sm", FILL[st])} />
            {STATUS_LABEL[st]}{" "}
            <span className="font-mono tabular-nums">{sums[st].toLocaleString()}</span>
          </li>
        ))}
      </ul>
    </figure>
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
