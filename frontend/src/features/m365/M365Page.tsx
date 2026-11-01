import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { api, type M365Overview, type PageWindow, type QueryResult } from "@/lib/api";
import { cn } from "@/lib/cn";
import { drillSql, openDrill } from "@/lib/drill";
import { navigate, useTab } from "@/lib/route";
import { PageHeader } from "@/components/shell/PageHeader";
import { LoadFailed } from "@/components/LoadFailed";
import { ResultsTable } from "@/features/search/ResultsTable";
import { DrillScope, DRILL, Kpi, SetCountries, Top, useDrill } from "@/features/dashboard/Sections";
import { TrendChart, TrendLegend } from "@/features/dashboard/TrendChart";
import { compareLine } from "@/features/dashboard/History";
import { WINDOWS, previousPhrase } from "@/features/dashboard/pageWindow";

const KEY = "m365.window";

function readWindow(): PageWindow {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "24h" || v === "7d" || v === "30d" ? v : "7d";
  } catch {
    return "7d";
  }
}

const hourFmt = (d: Date) => d.toLocaleTimeString("en-US", { hour: "numeric", timeZone: "UTC" });
const dayFmt = (d: Date) =>
  d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

/** Microsoft 365 (ADR-0038 section 5): Overview, then Sign-ins, Mail, Apps, and Admin as
 * event lists. One time window for the area; every number opens its rows (ADR-0039). */
export function M365Page() {
  const tab = useTab() ?? "overview";
  const [win, setWin] = useState<PageWindow>(readWindow);
  const q = useQuery({
    queryKey: ["m365-overview", win],
    queryFn: () => api.m365Overview(win),
    refetchInterval: 300_000,
  });
  const pick = (w: PageWindow) => {
    setWin(w);
    try {
      window.localStorage.setItem(KEY, w);
    } catch {
      // Storage blocked: the window still applies for this page view.
    }
  };
  const m = q.data;
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader title="Microsoft 365" />
      <div className="flex flex-col gap-4 p-5">
        <div className="flex flex-wrap items-center gap-3">
          <div role="group" aria-label="Time window" className="flex rounded border border-border">
            {WINDOWS.map((w) => (
              <button
                key={w.id}
                type="button"
                aria-pressed={w.id === win}
                onClick={() => pick(w.id)}
                className={cn(
                  "h-8 px-3 text-sm first:rounded-l last:rounded-r",
                  w.id === win
                    ? "bg-surface-head font-semibold text-text"
                    : "text-text-secondary hover:text-text",
                )}
              >
                {w.label}
              </button>
            ))}
          </div>
          {m ? (
            <span className="text-sm text-text-muted">
              {compareLine(m.history.compared, m.history.since, previousPhrase(win))}
            </span>
          ) : null}
        </div>
        {q.isLoading ? (
          <div aria-busy="true" className="h-64 animate-pulse rounded-card bg-surface" />
        ) : q.isError && !m ? (
          <section
            aria-label="Microsoft 365"
            className="rounded-card border border-border bg-surface"
          >
            <LoadFailed
              what="Microsoft 365"
              error={q.error}
              onRetry={() => void q.refetch()}
              retrying={q.isFetching}
            />
          </section>
        ) : !m ? null : !m.has_source ? (
          <section
            aria-label="Microsoft 365"
            className="rounded-card border border-border bg-surface p-5 text-sm"
          >
            <p className="mb-2 font-semibold">Needs a Microsoft 365 source</p>
            <p className="text-text-secondary">
              Add the Microsoft 365 connector, or a file read with a Microsoft 365 template, to see
              sign-ins, mail, apps, and admin changes here. If one exists, you may not have access
              to it.{" "}
              <button
                type="button"
                onClick={() => navigate("sources")}
                className="text-accent-text hover:underline"
              >
                Add a source
              </button>
            </p>
          </section>
        ) : (
          <DrillScope
            bounds={m}
            area={`Microsoft 365 > ${TAB_LABEL[tab] ?? "Overview"}`}
            history={m.history}
            before={previousPhrase(win)}
          >
            {tab === "sign-ins" ? (
              <EventList title="Sign-ins" sql={m.lists.sign_ins} m={m} />
            ) : tab === "mail" ? (
              <EventList title="Mail rules, forwarding, and DLP" sql={m.lists.mail} m={m} />
            ) : tab === "apps" ? (
              <>
                <EventList title="App consents" sql={m.lists.consents} m={m} />
                <EventList title="App registrations" sql={m.lists.registrations} m={m} />
              </>
            ) : tab === "admin" ? (
              <EventList title="Admin changes" sql={m.lists.admin} m={m} />
            ) : (
              <Overview m={m} />
            )}
          </DrillScope>
        )}
      </div>
    </div>
  );
}

const TAB_LABEL: Record<string, string> = {
  overview: "Overview",
  "sign-ins": "Sign-ins",
  mail: "Mail",
  apps: "Apps",
  admin: "Admin",
};

function Box({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section aria-label={label} className="rounded-card border border-border bg-surface">
      {children}
    </section>
  );
}

function Overview({ m }: { m: M365Overview }) {
  const drill = useDrill();
  const kpis = [
    <Kpi key="s" label="Sign-ins" kpi={m.sign_ins} />,
    <Kpi key="f" label="Failed sign-ins" kpi={m.failed} />,
    <Kpi
      key="o"
      label="Sign-ins outside approved countries"
      kpi={m.outside}
      context={m.outside ? "Successful sign-ins, by GeoIP of the address" : undefined}
      empty={<SetCountries />}
    />,
    <Kpi key="r" label="Risky sign-ins" kpi={m.risky} context="Medium or high risk" />,
    <Kpi
      key="c"
      label="App consents granted"
      kpi={m.consents}
      noun="consents"
      extra={
        m.consents?.extra
          ? {
              text: `${m.consents.extra.toLocaleString()} blocked`,
              label: "Blocked app consents",
              noun: "blocked consents",
            }
          : undefined
      }
    />,
    <Kpi
      key="a"
      label="Admin changes"
      kpi={m.admin_changes}
      noun="changes"
      context="Role grants and Conditional Access edits"
    />,
  ];
  return (
    <>
      <Box label="Overview">
        <div className="grid grid-cols-2 gap-px bg-border lg:grid-cols-3 min-[1400px]:grid-cols-6">
          {kpis}
        </div>
        <ul
          aria-label="Counts"
          className="flex flex-wrap gap-x-6 gap-y-1 border-t border-border px-3 py-2 text-sm"
        >
          {m.counts.map((c) => {
            const open = drill(c.kpi.drill, c.label);
            return (
              <li key={c.key} data-kpi={c.label} className="flex items-baseline gap-1.5">
                <span className="text-text-secondary">{c.label}</span>
                <button
                  type="button"
                  data-drill=""
                  onClick={open}
                  title={`Open ${c.kpi.value.toLocaleString()} events in Search`}
                  className={cn(DRILL, "font-mono font-semibold tabular-nums")}
                >
                  {c.kpi.value.toLocaleString()}
                </button>
              </li>
            );
          })}
        </ul>
      </Box>
      {m.outcome ? <Outcome m={m} /> : null}
      <div className="grid gap-4 lg:grid-cols-3">
        <Box label="Failure reasons">
          <div className="p-3">
            <Top
              title="Failure reasons"
              columns={["Reason", "Failed"]}
              rows={m.reasons}
              cells={(r) => [<RowLink key="r" row={r} />, r.count.toLocaleString()]}
              empty="No failed sign-ins in this window."
            />
          </div>
        </Box>
        <Box label="Sign-ins outside approved countries">
          <div className="p-3">
            {m.approved_set ? (
              <Top
                title="Sign-ins outside approved countries"
                columns={["Country", "People", "Sign-ins"]}
                rows={m.outside_top}
                cells={(r) => [<RowLink key="c" row={r} />, r.detail, r.count.toLocaleString()]}
                empty="No sign-ins outside approved countries in this window."
              />
            ) : (
              <>
                <h3 className="mb-2 text-sm font-semibold">Sign-ins outside approved countries</h3>
                <p className="text-sm text-text-secondary">
                  <SetCountries /> to see sign-ins from other countries.
                </p>
              </>
            )}
          </div>
        </Box>
        <Box label="Apps signed in to">
          <div className="p-3">
            <Top
              title="Apps signed in to"
              columns={["App", "Sign-ins"]}
              rows={m.apps}
              cells={(r) => [<RowLink key="a" row={r} />, r.count.toLocaleString()]}
              empty="No sign-ins in this window."
            />
          </div>
        </Box>
      </div>
    </>
  );
}

function RowLink({ row }: { row: M365Overview["reasons"][number] }) {
  const drill = useDrill();
  const open = drill(row.drill, row.label);
  return open ? (
    <button
      type="button"
      data-drill=""
      onClick={open}
      title={`Open ${row.count.toLocaleString()} events in Search`}
      className={cn(DRILL, "max-w-full truncate text-left")}
    >
      {row.label}
    </button>
  ) : (
    <>{row.label}</>
  );
}

/** Succeeded, interrupted, and failed (owner edit 2: failures in warn, interrupts muted,
 * never red): one bar of the window's split, then interrupts and failures over time. */
function Outcome({ m }: { m: M365Overview }) {
  const drill = useDrill();
  const o = m.outcome;
  if (!o) return null;
  const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);
  const parts = [
    { label: "Succeeded", n: sum(o.succeeded), color: "accent", sql: o.drill_succeeded },
    { label: "Interrupted", n: sum(o.interrupted), color: "text-muted", sql: o.drill_interrupted },
    { label: "Failed", n: sum(o.failed), color: "warn", sql: o.drill_failed },
  ];
  const total = Math.max(1, sum(parts.map((p) => p.n)));
  const hourly = m.window !== "30d";
  const at = (i: number) => new Date(o.points[i] ?? "");
  const name = (i: number) => (hourly ? `${dayFmt(at(i))}, ${hourFmt(at(i))} UTC` : dayFmt(at(i)));
  return (
    <Box label="Sign-in outcomes">
      <div className="grid gap-4 p-3 lg:grid-cols-[2fr_3fr]">
        <div className="min-w-0">
          <h3 className="mb-2 text-sm font-semibold">Sign-in outcomes</h3>
          <div className="flex h-5 overflow-hidden rounded-sm bg-border" aria-hidden="true">
            {parts.map((p) =>
              p.n ? (
                <div
                  key={p.label}
                  style={{ width: `${(p.n / total) * 100}%`, background: `var(--${p.color})` }}
                />
              ) : null,
            )}
          </div>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {parts.map((p) => (
              <li key={p.label} data-kpi={p.label} className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className="inline-block size-2.5 rounded-sm"
                  style={{ background: `var(--${p.color})` }}
                />
                <span className="text-text-secondary">{p.label}</span>
                <button
                  type="button"
                  data-drill=""
                  onClick={drill(p.sql, `${p.label} sign-ins`)}
                  title={`Open ${p.n.toLocaleString()} events in Search`}
                  className={cn(DRILL, "ml-auto font-mono tabular-nums")}
                >
                  {p.n.toLocaleString()}
                </button>
                <span className="w-12 text-right font-mono text-text-muted tabular-nums">
                  {((p.n / total) * 100).toFixed(1)}%
                </span>
              </li>
            ))}
          </ul>
        </div>
        <TrendChart
          title={`Interrupted and failed per ${hourly ? "hour" : "day"}`}
          stacked
          series={[
            { key: "i", label: "Interrupted", values: o.interrupted, color: "text-muted" },
            { key: "f", label: "Failed", values: o.failed, color: "warn" },
          ]}
          pointLabel={name}
          details={(i) =>
            [
              { label: "Top user", value: o.top_user?.[i] ?? "" },
              { label: "Top app", value: o.top_app?.[i] ?? "" },
            ].filter((d) => d.value)
          }
          axisLabel={(i) => (m.window === "24h" ? hourFmt(at(i)) : dayFmt(at(i)))}
          summary={`Interrupted and failed sign-ins per ${hourly ? "hour" : "day"}: ${sum(
            o.interrupted,
          ).toLocaleString()} interrupted, ${sum(o.failed).toLocaleString()} failed`}
          legend={
            <TrendLegend
              items={[
                { label: "Failed", color: "warn" },
                { label: "Interrupted", color: "text-muted" },
              ]}
            />
          }
          onOpen={(i) =>
            drill(o.drill_failed, `Failed sign-ins, ${name(i)}`, {
              from: o.points[i] ?? m.start,
              to: o.points[i + 1] ?? m.end,
            })?.()
          }
        />
      </div>
    </Box>
  );
}

/** One tab's events over the page window, in the Search table (ADR-0038 section 5). */
function EventList({ title, sql, m }: { title: string; sql: string; m: M365Overview }) {
  const filled = drillSql({ sql, from: m.start, to: m.end });
  const q = useQuery<QueryResult>({
    queryKey: ["m365-list", filled],
    queryFn: () => api.query({ sql: filled, start: m.start, end: m.end }),
  });
  return (
    <Box label={title}>
      <div className="flex items-center gap-3 border-b border-border px-3 py-2">
        <h2 className="text-base font-semibold">{title}</h2>
        {q.data ? (
          <span className="text-sm text-text-muted">
            {q.data.row_count.toLocaleString()}
            {q.data.truncated ? "+" : ""} rows
          </span>
        ) : null}
        <button
          type="button"
          onClick={() =>
            openDrill({ sql, from: m.start, to: m.end, origin: `Microsoft 365 > ${title}` })
          }
          className="ml-auto text-sm text-accent-text hover:underline"
        >
          Open in Search
        </button>
      </div>
      {q.isLoading ? (
        <div aria-busy="true" className="h-40 animate-pulse bg-surface" />
      ) : q.isError ? (
        <LoadFailed
          what={title}
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
        />
      ) : q.data && q.data.row_count === 0 ? (
        <p className="p-3 text-sm text-text-secondary">Nothing in this window.</p>
      ) : q.data ? (
        <ResultsTable result={q.data} view="parsed" compact geo={q.data.geo} />
      ) : null}
    </Box>
  );
}
