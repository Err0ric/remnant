import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  api,
  type DashboardSections,
  type PageWindow,
  type SectionKpi,
  type SectionRow,
  type SectionSeries,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { navigate } from "@/lib/route";
import { EntityLink } from "@/components/EntityLink";
import { LoadFailed } from "@/components/LoadFailed";
import { useViewer } from "@/lib/viewer";
import { previousPhrase } from "./pageWindow";

/** Round a chart's top up to 1, 2, or 5 times a power of ten. */
function niceTop(n: number): number {
  const p = 10 ** Math.floor(Math.log10(Math.max(1, n)));
  return ([1, 2, 5, 10].find((m) => m * p >= n) ?? 10) * p;
}

function bucketLabel(iso: string, w: PageWindow): string {
  const d = new Date(iso);
  return w === "24h"
    ? d.toLocaleTimeString("en-US", { hour: "numeric", timeZone: "UTC" })
    : d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

/** The change as a neutral pill beside the number: more is not good or bad by itself. */
function Delta({ kpi }: { kpi: SectionKpi }) {
  if (kpi.before === null) return null;
  const d = kpi.value - kpi.before;
  return (
    <span className="rounded-badge bg-surface-head px-1.5 font-mono text-xs font-semibold tabular-nums text-text">
      {d === 0 ? "same" : `${d > 0 ? "↑" : "↓"} ${Math.abs(d).toLocaleString()}`}
      <span className="sr-only"> against the window before</span>
    </span>
  );
}

interface KpiProps {
  label: string;
  kpi: SectionKpi | null;
  context?: ReactNode;
  /** Shown instead of a number when the count needs a setting or a source. */
  empty?: ReactNode;
}

function Kpi({ label, kpi, context, empty }: KpiProps) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 bg-surface px-3 py-2.5">
      <span className="truncate text-sm text-text-secondary" title={label}>
        {label}
      </span>
      {kpi ? (
        <span className="flex flex-wrap items-center gap-x-2">
          <span
            className={cn(
              "text-kpi tabular-nums min-[1500px]:text-kpi-lg",
              kpi.value === 0 ? "text-ok" : "text-text",
            )}
          >
            {kpi.value.toLocaleString()}
          </span>
          <Delta kpi={kpi} />
        </span>
      ) : (
        <span className="py-1.5 text-sm text-text-muted">{empty}</span>
      )}
      {context ? <span className="line-clamp-2 text-sm text-text-muted">{context}</span> : null}
    </div>
  );
}

function SetCountries() {
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

interface SectionProps {
  title: string;
  from?: string;
  window: PageWindow;
  note?: ReactNode;
  kpis: ReactNode;
  count: number;
  chart: ReactNode;
  table: ReactNode;
}

/** The page grammar: header, a KPI strip, then a chart and a top-N table. */
function Section({ title, from, window, note, kpis, count, chart, table }: SectionProps) {
  return (
    <section aria-label={title} className="rounded-card border border-border bg-surface">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 border-b border-border px-3 py-2">
        <h2 className="text-base font-semibold">{title}</h2>
        {from ? <span className="text-sm text-text-muted">from {from}</span> : null}
        <span className="ml-auto text-sm text-text-muted">
          Changes against {previousPhrase(window)}
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
  );
}

interface BarsProps {
  title: string;
  note: string;
  counts: number[];
  buckets: string[];
  window: PageWindow;
}

/** One series of bars in the warn tone (failures are routine, not severity; owner edit 2),
 * with a y axis of three ticks and dated x labels. */
function Bars({ title, note, counts, buckets, window }: BarsProps) {
  const top = niceTop(Math.max(2, ...counts));
  const mid = Math.floor((buckets.length - 1) / 2);
  const total = counts.reduce((a, b) => a + b, 0);
  return (
    <figure className="min-w-0">
      <figcaption className="mb-2 text-sm font-semibold">
        {title} <span className="font-normal text-text-muted">{note}</span>
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
          aria-label={`${title}: ${total.toLocaleString()} over ${counts.length} ${window === "24h" ? "hours" : "days"}`}
          className="relative flex h-28 items-end gap-px border-b border-l border-border"
        >
          <div
            aria-hidden="true"
            className="absolute inset-x-0 top-1/2 border-t border-dashed border-border"
          />
          {counts.map((n, i) => (
            <div
              key={buckets[i] ?? i}
              title={`${bucketLabel(buckets[i] ?? "", window)}: ${n.toLocaleString()}`}
              className="flex h-full min-w-0 flex-1 flex-col justify-end"
            >
              {n ? (
                <div className="bg-warn" style={{ height: `${Math.max(2, (n / top) * 100)}%` }} />
              ) : null}
            </div>
          ))}
        </div>
        <span />
        <div className="mt-1 flex justify-between font-mono text-xs tabular-nums text-text-muted">
          <span>{bucketLabel(buckets[0] ?? "", window)}</span>
          {buckets.length > 2 ? <span>{bucketLabel(buckets[mid] ?? "", window)}</span> : null}
          <span>{bucketLabel(buckets[buckets.length - 1] ?? "", window)}</span>
        </div>
      </div>
    </figure>
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
              return (
                <tr key={s.label} className="border-b border-border last:border-b-0">
                  <td
                    className={cn("max-w-0 truncate py-1.5 pr-3", mono ? "font-mono" : "")}
                    title={s.label}
                    style={{ width: "34%" }}
                  >
                    {s.label}
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
                          className={cn("min-w-0 flex-1", n ? "bg-accent" : "bg-border")}
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

function Top({ title, columns, rows, cells, empty }: TopProps) {
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
  const rate = id.sign_ins ? ((id.failed.value / id.sign_ins) * 100).toFixed(1) : "0";
  const kpis = [
    <Kpi key="f" label="Failed sign-ins" kpi={id.failed} />,
    <Kpi
      key="o"
      label="Sign-ins outside approved countries"
      kpi={id.outside}
      context={id.outside ? "Successful sign-ins, by GeoIP of the address" : undefined}
      empty={<SetCountries />}
    />,
    <Kpi key="i" label="Inbox rules and forwarding" kpi={id.inbox_rules} />,
    <Kpi
      key="c"
      label="App consents"
      kpi={id.consents}
      context={id.consents.extra ? `${id.consents.extra.toLocaleString()} blocked` : undefined}
    />,
    <Kpi key="r" label="Admin role grants" kpi={id.role_grants} />,
    <Kpi key="a" label="Conditional Access edits" kpi={id.ca_edits} />,
  ];
  return (
    <Section
      title="Identity"
      from="Microsoft 365"
      window={s.window}
      kpis={kpis}
      count={kpis.length}
      chart={
        <Bars
          title={`Failed sign-ins per ${s.window === "24h" ? "hour" : "day"}`}
          note={`${id.failed.value.toLocaleString()} of ${id.sign_ins.toLocaleString()} sign-ins failed (${rate}%)`}
          counts={id.failed_by_bucket}
          buckets={s.buckets}
          window={s.window}
        />
      }
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
    <Kpi key="a" label="Attacking addresses" kpi={a.addresses} />,
    <Kpi key="c" label="Countries" kpi={a.countries} empty="Needs a GeoIP file" />,
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
      window={s.window}
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
      table={
        <Top
          title="Top sources"
          columns={["Country", "Network", "Addresses", "Failures"]}
          rows={a.top_sources}
          cells={(r) => {
            const [network = "", addresses = ""] = r.detail.split("|");
            return [
              r.label,
              <span key="n" className="font-mono" title={network}>
                {network || "Unknown"}
              </span>,
              <span key="a" className="font-mono tabular-nums">
                {addresses}
              </span>,
              r.count.toLocaleString(),
            ];
          }}
          empty="No external failures in this window."
        />
      }
    />
  );
}

function Detections({ s }: { s: DashboardSections }) {
  const d = s.detections;
  if (!d) return null;
  const kpis = [
    <Kpi key="m" label="Rule matches" kpi={d.matches} />,
    <Kpi
      key="r"
      label="Rules that matched"
      kpi={d.rules_matched}
      context={
        d.rules_matched.extra !== null
          ? `of ${d.rules_matched.extra.toLocaleString()} enabled`
          : undefined
      }
    />,
    <Kpi key="h" label="Hosts involved" kpi={d.hosts} />,
    <Kpi key="u" label="Users involved" kpi={d.users} />,
  ];
  return (
    <Section
      title="Detections"
      window={s.window}
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
