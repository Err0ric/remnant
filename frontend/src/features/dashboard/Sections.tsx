import { createContext, useContext, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  type DashboardSections,
  type PageWindow,
  type SectionKpi,
  type SectionHistory,
  type SectionRow,
  type SectionSeries,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { navigate } from "@/lib/route";
import { openDrill } from "@/lib/drill";
import { EntityLink } from "@/components/EntityLink";
import { LoadFailed } from "@/components/LoadFailed";
import { useViewer } from "@/lib/viewer";
import { previousPhrase } from "./pageWindow";
import { TrendChart, TrendLegend } from "./TrendChart";
import { compareLine, NoHistory } from "./History";

/** The section around a card: its comparison state and what drill-throughs need. */
/** The window a section counts over: its start, now, and the start of the one before. */
export type Bounds = Pick<DashboardSections, "start" | "end" | "before">;

interface Ctx {
  history: SectionHistory;
  before: string;
  title: string;
  s: Bounds | null;
  /** Where the page is, for Search's origin line ("Dashboard", "Microsoft 365 > Overview"). */
  area: string;
}
const Compare = createContext<Ctx>({
  history: { compared: true, since: null },
  before: "",
  title: "",
  s: null,
  area: "Dashboard",
});

type Span = "now" | "before" | { from: string; to: string };

/** Opens a number's rows in Search (ADR-0039): the page window, the window before, or one
 * chart point. Undefined when the server sent no query. */
export function useDrill() {
  const c = useContext(Compare);
  return (sql: string | null | undefined, label: string, span: Span = "now") => {
    if (!sql || !c.s) return undefined;
    const s = c.s;
    const [from, to] =
      span === "now"
        ? [s.start, s.end]
        : span === "before"
          ? [s.before, s.start]
          : [span.from, span.to];
    const where = c.title ? `${c.area} > ${c.title}` : c.area;
    return () => openDrill({ sql, from, to, origin: `${where} > ${label}` });
  };
}

export const DRILL =
  "cursor-pointer rounded-sm decoration-1 underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-1 focus-visible:outline-focus-ring";

function bucketLabel(iso: string, w: PageWindow): string {
  const d = new Date(iso);
  return w === "24h"
    ? d.toLocaleTimeString("en-US", { hour: "numeric", timeZone: "UTC" })
    : d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

/** The change as a neutral pill beside the number: more is not good or bad by itself.
 * It opens the same search over the window before. */
function Delta({ kpi, label, noun }: { kpi: SectionKpi; label: string; noun: string }) {
  const { before } = useContext(Compare);
  const drill = useDrill();
  if (kpi.before === null) return null;
  const d = kpi.value - kpi.before;
  const open = drill(kpi.drill_before ?? kpi.drill, `${label} (${before})`, "before");
  const text = d === 0 ? "same" : `${d > 0 ? "↑" : "↓"} ${Math.abs(d).toLocaleString()}`;
  const cls =
    "rounded-badge bg-surface-head px-1.5 font-mono text-xs font-semibold tabular-nums text-text";
  if (!open)
    return (
      <span className={cls}>
        {text}
        <span className="sr-only"> against the window before</span>
      </span>
    );
  return (
    <button
      type="button"
      data-drill=""
      onClick={open}
      title={`Open ${kpi.before.toLocaleString()} ${noun} from ${before} in Search`}
      className={cn(
        cls,
        "cursor-pointer hover:bg-border focus-visible:outline focus-visible:outline-1 focus-visible:outline-focus-ring",
      )}
    >
      {text}
      <span className="sr-only"> against the window before; open its {noun} in Search</span>
    </button>
  );
}

export interface KpiProps {
  label: string;
  kpi: SectionKpi | null;
  /** What the number counts, for "Open 12 events in Search". */
  noun?: string;
  context?: ReactNode;
  /** A sub-line with its own list ("2 blocked"): opens `kpi.extra_drill`. */
  extra?: { text: string; label: string; noun: string };
  /** Shown instead of a number when the count needs a setting or a source. */
  empty?: ReactNode;
}

export function Kpi({ label, kpi, noun = "events", context, extra, empty }: KpiProps) {
  const { history, before } = useContext(Compare);
  const drill = useDrill();
  const partial = !history.compared && kpi !== null && kpi.before !== null;
  const open = kpi ? drill(kpi.drill, label) : undefined;
  const openExtra = kpi && extra ? drill(kpi.extra_drill, extra.label) : undefined;
  const value = kpi ? (
    <span
      className={cn(
        "text-kpi tabular-nums min-[1500px]:text-kpi-lg",
        kpi.value === 0 ? "text-ok" : "text-text",
      )}
    >
      {kpi.value.toLocaleString()}
    </span>
  ) : null;
  return (
    <div data-kpi={label} className="flex min-w-0 flex-col gap-0.5 bg-surface px-3 py-2.5">
      <span className="truncate text-sm text-text-secondary" title={label}>
        {label}
      </span>
      {kpi ? (
        <span className="flex flex-wrap items-center gap-x-2">
          {open ? (
            <button
              type="button"
              data-drill=""
              onClick={open}
              title={`Open ${kpi.value.toLocaleString()} ${noun} in Search`}
              aria-label={`${label}: ${kpi.value.toLocaleString()}. Open ${noun} in Search`}
              className={DRILL}
            >
              {value}
            </button>
          ) : (
            value
          )}
          {partial ? null : <Delta kpi={kpi} label={label} noun={noun} />}
        </span>
      ) : (
        <span className="py-1.5 text-sm text-text-muted">{empty}</span>
      )}
      {partial ? <NoHistory since={history.since} before={before} /> : null}
      {openExtra && extra ? (
        <button
          type="button"
          data-drill=""
          onClick={openExtra}
          title={`Open ${extra.noun} in Search`}
          className={cn(DRILL, "self-start text-sm text-text-muted")}
        >
          {extra.text}
        </button>
      ) : null}
      {context ? <span className="line-clamp-2 text-sm text-text-muted">{context}</span> : null}
    </div>
  );
}

export function SetCountries() {
  const { isAdmin } = useViewer();
  return isAdmin ? (
    <button
      type="button"
      onClick={() => navigate("enrichment")}
      className="text-accent-text hover:underline"
    >
      Set approved countries
    </button>
  ) : (
    <>Approved countries not set</>
  );
}

/** Gives cards outside a Dashboard section what drill-throughs need. */
export function DrillScope({
  bounds,
  area,
  title = "",
  history = { compared: true, since: null },
  before,
  children,
}: {
  bounds: Bounds;
  area: string;
  title?: string;
  history?: SectionHistory;
  before: string;
  children: ReactNode;
}) {
  return (
    <Compare.Provider value={{ history, before, title, s: bounds, area }}>
      {children}
    </Compare.Provider>
  );
}

interface SectionProps {
  title: string;
  from?: string;
  s: Bounds;
  window: PageWindow;
  history: SectionHistory;
  note?: ReactNode;
  kpis: ReactNode;
  count: number;
  chart: ReactNode;
  table: ReactNode;
}

/** The page grammar: header, a KPI strip, then a chart and a top-N table. */
function Section({
  title,
  from,
  s,
  window,
  history,
  note,
  kpis,
  count,
  chart,
  table,
}: SectionProps) {
  const before = previousPhrase(window);
  return (
    <Compare.Provider value={{ history, before, title, s, area: "Dashboard" }}>
      <section aria-label={title} className="rounded-card border border-border bg-surface">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-border px-3 py-2">
          <h2 className="text-base font-semibold">{title}</h2>
          {from ? <span className="text-sm text-text-muted">from {from}</span> : null}
          <span className="ml-auto text-sm text-text-muted">
            {compareLine(history.compared, history.since, before)}
          </span>
        </div>
        {note ? <div className="border-b border-border px-3 py-1.5 text-sm">{note}</div> : null}
        <div
          className={cn(
            "grid gap-px bg-border",
            count === 4
              ? "grid-cols-2 lg:grid-cols-4"
              : "grid-cols-2 lg:grid-cols-[repeat(auto-fit,minmax(150px,1fr))]",
          )}
        >
          {kpis}
        </div>
        <div className="grid min-w-0 gap-4 border-t border-border p-3 lg:grid-cols-2 min-[1500px]:grid-cols-[3fr_2fr]">
          <div className="min-w-0">{chart}</div>
          <div className="min-w-0">{table}</div>
        </div>
      </section>
    </Compare.Provider>
  );
}

const hourFmt = (d: Date) => d.toLocaleTimeString("en-US", { hour: "numeric", timeZone: "UTC" });
const dayFmt = (d: Date) =>
  d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

/** Failed sign-ins over the window: one amber line (failures are routine, not severity;
 * owner edit 2), hourly through 7 days, with the window before dashed. */
function FailedTrend({ s }: { s: DashboardSections }) {
  const drill = useDrill();
  const id = s.identity;
  if (!id) return null;
  const t = id.failed_trend;
  const hourly = s.window !== "30d";
  const at = (i: number) => new Date(t.points[i] ?? "");
  const rate = id.sign_ins ? ((id.failed.value / id.sign_ins) * 100).toFixed(1) : "0";
  const before = previousPhrase(s.window).replace(/^the p/, "P");
  const pointName = (i: number) =>
    hourly ? `${dayFmt(at(i))}, ${hourFmt(at(i))} UTC` : dayFmt(at(i));
  return (
    <TrendChart
      title={`Failed sign-ins per ${hourly ? "hour" : "day"}`}
      note={`${id.failed.value.toLocaleString()} of ${id.sign_ins.toLocaleString()} sign-ins failed (${rate}%)`}
      series={[{ key: "failed", label: "Failed sign-ins", values: t.counts, color: "warn" }]}
      onOpen={(i) =>
        drill(id.failed.drill, `Failed sign-ins, ${pointName(i)}`, {
          from: t.points[i] ?? s.start,
          to: t.points[i + 1] ?? s.end,
        })?.()
      }
      previous={id.history.compared ? { label: before, values: t.before } : undefined}
      pointLabel={(i) => (hourly ? `${dayFmt(at(i))}, ${hourFmt(at(i))} UTC` : dayFmt(at(i)))}
      axisLabel={(i) => (s.window === "24h" ? hourFmt(at(i)) : dayFmt(at(i)))}
      summary={`Failed sign-ins per ${hourly ? "hour" : "day"}: ${id.failed.value.toLocaleString()} in this window${
        id.history.compared
          ? `, ${t.before.reduce((a, b) => a + b, 0).toLocaleString()} in the window before`
          : ""
      }`}
      legend={
        <TrendLegend
          items={[
            { label: "This window", color: "warn" },
            ...(id.history.compared ? [{ label: before, dashed: true }] : []),
          ]}
        />
      }
    />
  );
}

interface MultiplesProps {
  title: string;
  series: SectionSeries[];
  buckets: string[];
  window: PageWindow;
  mono?: boolean;
  empty: string;
}

/** Small multiples: one row of bars per host or rule on its own scale, with its peak and
 * total, instead of a stack of colors (severity colors stay reserved; call 5). */
function Multiples({ title, series, buckets, window, mono, empty }: MultiplesProps) {
  const drill = useDrill();
  return (
    <figure className="min-w-0">
      <figcaption className="mb-2 text-sm font-semibold">
        {title}{" "}
        <span className="font-normal text-text-muted">
          per {window === "24h" ? "hour" : "day"}, each row on its own scale
        </span>
      </figcaption>
      {series.length === 0 ? (
        <p className="text-sm text-text-secondary">{empty}</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="sr-only">
            <tr>
              <th>Name</th>
              <th>Per {window === "24h" ? "hour" : "day"}</th>
              <th>Peak</th>
              <th>Total</th>
            </tr>
          </thead>
          <tbody>
            {series.map((s) => {
              const peak = Math.max(...s.counts);
              const total = s.counts.reduce((a, b) => a + b, 0);
              const open = drill(s.drill, `${title} > ${s.label}`);
              return (
                <tr
                  key={s.label}
                  data-row={s.label}
                  onClick={open}
                  className={cn(
                    "border-b border-border last:border-b-0",
                    open && "cursor-pointer hover:bg-surface-head",
                  )}
                >
                  <td
                    className={cn("max-w-0 truncate py-1.5 pr-3", mono ? "font-mono" : "")}
                    title={s.label}
                    style={{ width: "34%" }}
                  >
                    {open ? (
                      <button
                        type="button"
                        data-drill=""
                        onClick={(e) => {
                          e.stopPropagation();
                          open();
                        }}
                        title={`Open ${total.toLocaleString()} events in Search`}
                        className={cn(DRILL, "max-w-full truncate text-left")}
                      >
                        {s.label}
                      </button>
                    ) : (
                      s.label
                    )}
                  </td>
                  <td className="py-1.5 pr-3" style={{ width: "46%" }}>
                    <div
                      role="img"
                      aria-label={`${s.label}: peak ${peak}, total ${total}`}
                      className="flex h-5 items-end gap-px"
                    >
                      {s.counts.map((n, i) => (
                        <div
                          key={buckets[i] ?? i}
                          title={`${bucketLabel(buckets[i] ?? "", window)}: ${n}`}
                          className={cn("min-w-0 max-w-5 flex-1", n ? "bg-accent" : "bg-border")}
                          style={{
                            height: n ? `${Math.max(12, (n / Math.max(1, peak)) * 100)}%` : "1px",
                          }}
                        />
                      ))}
                    </div>
                  </td>
                  <td className="whitespace-nowrap py-1.5 pr-3 text-right font-mono tabular-nums text-text-secondary">
                    peak {peak.toLocaleString()}
                  </td>
                  <td className="whitespace-nowrap py-1.5 text-right font-mono tabular-nums">
                    {total.toLocaleString()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </figure>
  );
}

interface TopProps {
  title: string;
  columns: string[];
  rows: SectionRow[];
  cells: (r: SectionRow) => ReactNode[];
  empty: string;
}

export function Top({ title, columns, rows, cells, empty }: TopProps) {
  return (
    <div className="min-w-0">
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-sm text-text-secondary">{empty}</p>
      ) : (
        <div className="overflow-x-auto">
          <table aria-label={title} className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-secondary">
                {columns.map((c, i) => (
                  <th
                    key={c}
                    className={cn(
                      "py-1 pr-3 font-semibold",
                      i === columns.length - 1 && "pr-0 text-right",
                    )}
                  >
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={`${r.kind}:${r.label}:${r.detail}`}
                  data-row={r.label}
                  className="border-b border-border last:border-b-0"
                >
                  {cells(r).map((c, i, all) => (
                    <td
                      key={i}
                      className={cn(
                        "max-w-0 truncate py-1.5 pr-3",
                        i === all.length - 1 && "pr-0 text-right font-mono tabular-nums",
                      )}
                    >
                      {c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Identity({ s }: { s: DashboardSections }) {
  const id = s.identity;
  if (!id) return null;
  const kpis = [
    <Kpi key="f" label="Failed sign-ins" kpi={id.failed} />,
    <Kpi
      key="o"
      label="Sign-ins outside approved countries"
      kpi={id.outside}
      context={id.outside ? "Successful sign-ins, by GeoIP of the address" : undefined}
      empty={<SetCountries />}
    />,
    <Kpi key="i" label="Inbox rules and forwarding" kpi={id.inbox_rules} noun="changes" />,
    <Kpi
      key="c"
      label="App consents"
      kpi={id.consents}
      noun="consents"
      extra={
        id.consents.extra
          ? {
              text: `${id.consents.extra.toLocaleString()} blocked`,
              label: "Blocked app consents",
              noun: "blocked consents",
            }
          : undefined
      }
    />,
    <Kpi key="r" label="Admin role grants" kpi={id.role_grants} noun="changes" />,
    <Kpi key="a" label="Conditional Access edits" kpi={id.ca_edits} noun="changes" />,
  ];
  return (
    <Section
      title="Identity"
      s={s}
      from="Microsoft 365"
      window={s.window}
      history={id.history}
      kpis={kpis}
      count={kpis.length}
      chart={<FailedTrend s={s} />}
      table={
        <Top
          title="Top failing users"
          columns={["User", "Failed"]}
          rows={id.top_failing}
          cells={(r) => [
            <EntityLink key="u" kind="user" value={r.label} className="font-mono" />,
            r.count.toLocaleString(),
          ]}
          empty="No failed sign-ins in this window."
        />
      }
    />
  );
}

function Attacks({ s }: { s: DashboardSections }) {
  const { isAdmin } = useViewer();
  const a = s.attacks;
  if (!a) return null;
  const kpis = [
    <Kpi
      key="f"
      label="External sign-in failures"
      kpi={a.failures}
      context="SSH, Windows, VPN, and other logins"
    />,
    <Kpi key="a" label="Attacking addresses" kpi={a.addresses} noun="addresses" />,
    <Kpi key="c" label="Countries" kpi={a.countries} noun="countries" empty="Needs a GeoIP file" />,
    <Kpi
      key="v"
      label="VPN logins outside approved countries"
      kpi={a.vpn_outside}
      empty={a.has_vpn ? <SetCountries /> : "No VPN logs"}
    />,
  ];
  return (
    <Section
      title="Attacks and access"
      s={s}
      window={s.window}
      history={a.history}
      note={
        !s.has_public ? (
          <span className="text-text-secondary">
            Company egress addresses are not listed, so office addresses count as external.{" "}
            {isAdmin ? (
              <button
                type="button"
                onClick={() => navigate("enrichment")}
                className="text-accent-text hover:underline"
              >
                Add internal networks
              </button>
            ) : null}
          </span>
        ) : undefined
      }
      kpis={kpis}
      count={kpis.length}
      chart={
        <Multiples
          title="Failures by host"
          series={a.by_host}
          buckets={s.buckets}
          window={s.window}
          mono
          empty="No failures from external addresses in this window."
        />
      }
      table={<TopSources s={s} rows={a.top_sources} />}
    />
  );
}

// Why an address has no country (app.search.dashboard.unplaced).
const NOT_IN_GEOIP = "Not in GeoIP file";
const UNPLACED = new Set(["Not an address", "Not a public address", NOT_IN_GEOIP, "No GeoIP file"]);

/** Top sources by country and network. Addresses with no country say why, and when the
 * GeoIP file does not list them, admins are offered the update (owner 2026-10-30). */
function TopSources({ s, rows }: { s: DashboardSections; rows: SectionRow[] }) {
  const { isAdmin } = useViewer();
  const drill = useDrill();
  const missing = rows.find((r) => r.label === NOT_IN_GEOIP);
  const fileDate = s.geoip_date
    ? new Date(s.geoip_date).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        timeZone: "UTC",
      })
    : null;
  return (
    <div className="min-w-0">
      <Top
        title="Top sources"
        columns={["Country", "Network", "Addresses", "Failures"]}
        rows={rows}
        cells={(r) => {
          const [network = "", addresses = ""] = r.detail.split("|");
          const why = UNPLACED.has(r.label);
          const open = drill(r.drill, `Top sources > ${r.label}${network ? `, ${network}` : ""}`);
          const place = why ? (
            <span
              key="c"
              className="text-text-secondary"
              title={
                r.label === NOT_IN_GEOIP && fileDate
                  ? `Public addresses the GeoIP file (installed ${fileDate}) does not list`
                  : r.label
              }
            >
              {r.label}
            </span>
          ) : (
            r.label
          );
          return [
            open ? (
              <button
                key="c"
                type="button"
                data-drill=""
                onClick={open}
                title={`Open ${r.count.toLocaleString()} events in Search`}
                className={cn(DRILL, "max-w-full truncate text-left")}
              >
                {place}
              </button>
            ) : (
              place
            ),
            <span key="n" className="font-mono" title={network}>
              {network || (why ? "" : "Unknown")}
            </span>,
            <span key="a" className="font-mono tabular-nums">
              {addresses}
            </span>,
            r.count.toLocaleString(),
          ];
        }}
        empty="No external failures in this window."
      />
      {missing ? (
        <p role="note" className="mt-2 text-sm text-text-secondary">
          {Number(missing.detail.split("|")[1] ?? 0).toLocaleString()} addresses are not in the
          GeoIP file{fileDate ? ` (installed ${fileDate})` : ""}.{" "}
          {isAdmin ? (
            <button
              type="button"
              onClick={() => navigate("enrichment")}
              className="text-accent-text hover:underline"
            >
              Update GeoIP
            </button>
          ) : (
            "An admin can update it in Settings > Enrichment."
          )}
        </p>
      ) : null}
    </div>
  );
}

function Detections({ s }: { s: DashboardSections }) {
  const d = s.detections;
  if (!d) return null;
  const kpis = [
    <Kpi key="m" label="Rule matches" kpi={d.matches} noun="matched events" />,
    <Kpi
      key="r"
      label="Rules that matched"
      kpi={d.rules_matched}
      noun="matches"
      context={
        d.rules_matched.extra !== null ? (
          <button
            type="button"
            data-drill=""
            onClick={() => navigate("rules")}
            title="Open the rules"
            className={DRILL}
          >
            of {d.rules_matched.extra.toLocaleString()} enabled
          </button>
        ) : undefined
      }
    />,
    <Kpi key="h" label="Hosts involved" kpi={d.hosts} noun="hosts" />,
    <Kpi key="u" label="Users involved" kpi={d.users} noun="people" />,
  ];
  return (
    <Section
      title="Detections"
      s={s}
      window={s.window}
      history={d.history}
      kpis={kpis}
      count={kpis.length}
      chart={
        <Multiples
          title="Matches by rule"
          series={d.by_rule}
          buckets={s.buckets}
          window={s.window}
          empty="No rule matched in this window."
        />
      }
      table={
        <Top
          title="Hosts and users involved"
          columns={["", "Name", "Matches"]}
          rows={d.involved}
          cells={(r) => [
            <span key="k" className="text-text-muted">
              {r.kind === "host" ? "Host" : "User"}
            </span>,
            <EntityLink
              key="v"
              kind={r.kind === "host" ? "host" : "user"}
              value={r.label}
              className="font-mono"
            />,
            r.count.toLocaleString(),
          ]}
          empty="No hosts or users in this window's matches."
        />
      }
    />
  );
}

/** Identity, Attacks and access, and Detections (ADR-0038 edit 10), each shown only when
 * the viewer has its source. */
export function Sections({ window }: { window: PageWindow }) {
  const q = useQuery({
    queryKey: ["dashboard-sections", window],
    queryFn: () => api.dashboardSections(window),
    refetchInterval: 300_000,
  });
  if (q.isLoading)
    return <div aria-busy="true" className="h-48 animate-pulse rounded-card bg-surface" />;
  if (q.isError && !q.data)
    return (
      <section aria-label="Sections" className="rounded-card border border-border bg-surface">
        <LoadFailed
          what="the Dashboard sections"
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
        />
      </section>
    );
  const s = q.data;
  if (!s) return null;
  return (
    <>
      <Identity s={s} />
      <Attacks s={s} />
      <Detections s={s} />
    </>
  );
}
