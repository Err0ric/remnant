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
import { EntityLink } from "@/components/EntityLink";
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

/** AI Watch (ADR-0035 Part 2): is anyone using AI we have not approved? Five cards, AI use
 * over 30 days by review status, and the top services, on the viewer's own sources.
 * Hidden on an install with no AI use and nothing to count. */
export function AiWatch() {
  const [days, setDays] = useState<(typeof RANGES)[number]>(7);
  const q = useQuery({
    queryKey: ["ai-watch", days],
    queryFn: () => api.aiWatchSummary(days),
    refetchInterval: 300_000,
  });
  if (q.isLoading)
    return <div aria-busy="true" className="h-48 animate-pulse rounded-card bg-surface" />;
  const s = q.data;
  if (!s) return null;
  const used = s.chart.some((d) => d.approved + d.unreviewed + d.not_approved > 0);
  if (!used && !s.cards.some((c) => (c.value ?? 0) > 0)) return null;
  const shown = s.cards.filter((c) => !c.needs);
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
        <Chart chart={s.chart} />
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
          {labels.join(", ").toLowerCase()} (needs {need})
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

function Card({ card, days, odd }: { card: AiWatchCard; days: number; odd: boolean }) {
  const link =
    card.key === "agents"
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
      <span className="truncate text-sm text-text-secondary" title={card.label}>
        {card.label}
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
          <span className="text-sm text-text-secondary">{delta(card, days)}</span>
          <span className="truncate text-sm text-text-muted" title={card.context}>
            {card.context}
          </span>
        </>
      )}
    </div>
  );
}

function Chart({ chart: all }: { chart: AiWatchDay[] }) {
  const total = (d: AiWatchDay) => d.approved + d.unreviewed + d.not_approved;
  // With less than 7 days of data, the chart covers the days that exist (F62).
  const first = all.findIndex((d) => total(d) > 0);
  const chart = first > 0 && all.length - first < 7 ? all.slice(first) : all;
  const top = Math.max(1, ...chart.map(total));
  const sums = Object.fromEntries(
    ORDER.map((st) => [st, chart.reduce((n, d) => n + d[st], 0)]),
  ) as Record<AiStatus, number>;
  const summary = ORDER.map((st) => `${STATUS_LABEL[st]} ${sums[st].toLocaleString()}`).join(", ");
  const label = (iso: string) =>
    new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return (
    <figure className="min-w-0">
      <figcaption className="mb-2 text-sm font-semibold">
        {chart.length < all.length
          ? `AI use since ${label(chart[0]?.day ?? "")}`
          : "AI use, last 30 days"}{" "}
        <span className="font-normal text-text-muted">events per day</span>
      </figcaption>
      <div
        role="img"
        aria-label={`AI use per day over ${chart.length} days by review status: ${summary}`}
        className="flex h-28 items-end gap-px"
      >
        {chart.map((d) => (
          <div
            key={d.day}
            title={`${label(d.day)}: ${ORDER.map((st) => `${STATUS_LABEL[st]} ${d[st].toLocaleString()}`).join(", ")}`}
            className="flex h-full min-w-0 flex-1 flex-col justify-end"
          >
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
        ))}
      </div>
      <div className="mt-1 flex justify-between font-mono text-xs tabular-nums text-text-muted">
        <span>{label(chart[0]?.day ?? "")}</span>
        <span>today</span>
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
