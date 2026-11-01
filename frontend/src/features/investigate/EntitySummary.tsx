import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { EntityLink } from "@/components/EntityLink";
import { When } from "@/components/When";
import { ApiError, api, type EntitySummary as Summary } from "@/lib/api";

interface EntitySummaryProps {
  kind: "user" | "ip" | "host";
  value: string;
  start: string | undefined;
  /** The range's id, for caching: `start` moves with the clock. */
  range: string;
  /** "the last 7 days" */
  rangeWords: string;
  onSearch: (sql: string) => void;
}

function n(x: number): string {
  return x.toLocaleString();
}

function plural(x: number, one: string, many: string): string {
  return `${n(x)} ${x === 1 ? one : many}`;
}

/** The page's answer in one sentence (product pass, "lead with the answer"). */
export function finding(s: Summary, rangeWords: string): string {
  if (!s.events)
    return `Nothing from this ${s.kind === "ip" ? "address" : s.kind === "user" ? "person" : "machine"} in ${rangeWords}, in the sources you may read.`;
  const hosts = s.targets.filter((t) => t.kind === "host");
  const top = hosts[0] && hosts[0].events >= s.events / 2 ? hosts[0].value : null;
  const where = s.geo?.country_name
    ? ` From ${s.geo.country_name}${s.geo.asn ? `, AS${s.geo.asn}` : ""}${s.geo.org ? ` ${s.geo.org}` : ""}.`
    : "";
  if (s.kind === "ip" && s.failed)
    return `${plural(s.failed, "failed sign-in", "failed sign-ins")}${top ? ` against ${top}` : hosts.length > 1 ? ` against ${n(hosts.length)} hosts` : ""} over ${rangeWords}, ${n(s.succeeded)} succeeded.${where}`;
  if (s.kind === "user")
    return `${plural(s.sign_ins, "sign-in", "sign-ins")} (${n(s.failed)} failed) from ${plural(s.addresses, "address", "addresses")} to ${plural(s.hosts, "host", "hosts")} over ${rangeWords}.`;
  if (s.kind === "host" && s.sign_ins)
    return `${plural(s.events, "event", "events")} over ${rangeWords}; ${plural(s.failed, "failed sign-in", "failed sign-ins")} by ${plural(s.users, "user", "users")}, ${n(s.succeeded)} succeeded.`;
  return `${plural(s.events, "event", "events")} from ${plural(s.sources.length, "source", "sources")} over ${rangeWords}.${where}`;
}

function Kpi({
  label,
  value,
  tone,
  small,
}: {
  label: string;
  value: ReactNode;
  tone?: string;
  small?: boolean;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 rounded-card border border-border bg-surface px-3 py-2">
      <span className="text-sm text-text-secondary">{label}</span>
      <span
        className={`${small ? "text-base" : "text-lg"} font-semibold tabular-nums [overflow-wrap:anywhere] ${tone ?? ""}`}
      >
        {value}
      </span>
    </div>
  );
}

const OUTCOME: Record<string, string> = {
  succeeded: "Succeeded",
  failed: "Failed",
  other: "Other",
};

/** Neutral badges; only a success from an outside address is alert-worthy. */
function tone(kind: string, outcome: string): string {
  if (kind === "ip" && outcome === "succeeded") return "bg-sev-high-bg text-sev-high-text";
  return "bg-surface-head text-text-secondary";
}

/** The top of an entity's page (DESIGN 6.2): the finding, KPI cards, activities grouped by
 * outcome with a real line each, and what it touched. Every value is a pivot link. */
export function EntitySummary({
  kind,
  value,
  start,
  range,
  rangeWords,
  onSearch,
}: EntitySummaryProps) {
  const q = useQuery({
    queryKey: ["entity-summary", kind, value, range],
    queryFn: () => api.entitySummary({ kind, value, start }),
    staleTime: 60_000,
  });
  if (q.isPending)
    return (
      <div aria-busy="true" className="flex flex-col gap-3">
        <div className="h-6 w-2/3 animate-pulse rounded bg-surface-head" />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-[4.5rem] animate-pulse rounded-card bg-surface-head" />
          ))}
        </div>
      </div>
    );
  if (q.error)
    return (
      <p role="alert" className="text-sm text-danger">
        {q.error instanceof ApiError ? q.error.message : "Could not load this entity's summary"}
      </p>
    );
  const s = q.data;
  const hosts = s.targets.filter((t) => t.kind === "host");
  const users = s.targets.filter((t) => t.kind === "user");
  const kpis: ReactNode[] =
    kind === "ip"
      ? [
          <Kpi key="a" label="Sign-in attempts" value={n(s.sign_ins)} />,
          <Kpi
            key="s"
            label="Succeeded"
            value={n(s.succeeded)}
            tone={s.succeeded ? "text-danger" : ""}
          />,
          <Kpi key="u" label="Users tried" value={n(s.users)} />,
          <Kpi key="h" label="Hosts targeted" value={n(s.hosts)} />,
        ]
      : kind === "user"
        ? [
            <Kpi key="a" label="Sign-ins" value={n(s.sign_ins)} />,
            <Kpi key="f" label="Failed" value={n(s.failed)} />,
            <Kpi
              key="ad"
              label="From addresses"
              value={
                <span
                  title={
                    s.service_addresses
                      ? `${n(s.service_addresses)} Microsoft 365 service addresses on server-side records are not counted`
                      : undefined
                  }
                >
                  {n(s.addresses)}
                  {s.service_addresses ? (
                    <span className="ml-1.5 text-sm font-normal text-text-muted">
                      + {n(s.service_addresses)} Microsoft 365
                    </span>
                  ) : null}
                </span>
              }
            />,
            <Kpi key="h" label="Hosts" value={n(s.hosts)} />,
          ]
        : [
            <Kpi key="e" label="Events" value={n(s.events)} />,
            <Kpi key="f" label="Failed sign-ins" value={n(s.failed)} />,
            <Kpi key="u" label="Users" value={n(s.users)} />,
            <Kpi key="ad" label="Addresses" value={n(s.addresses)} />,
          ];
  return (
    <section aria-label="Summary" className="flex flex-col gap-3">
      <p className="text-md">{finding(s, rangeWords)}</p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {kpis}
        <Kpi label="First seen" small value={<When iso={s.first_seen} />} />
        <Kpi label="Last seen" small value={<When iso={s.last_seen} />} />
        {kind === "ip" && s.geo ? (
          <Kpi
            label="Country and network"
            value={`${s.geo.country ?? "?"}${s.geo.asn ? ` · AS${s.geo.asn}` : ""}`}
          />
        ) : null}
      </div>
      {s.activities.length ? (
        <div className="overflow-hidden rounded-card border border-border bg-surface">
          <h2 className="border-b border-border px-3 py-2 text-sm font-semibold">
            What it did <span className="font-normal text-text-muted">by outcome</span>
          </h2>
          <ul aria-label="Activities">
            {s.activities.map((a, i) => (
              <li
                key={i}
                className="grid grid-cols-1 gap-x-3 gap-y-1 border-b border-border px-3 py-2 text-sm last:border-0 md:grid-cols-[6rem_minmax(0,1fr)_7rem_auto]"
              >
                <span>
                  <span
                    className={`rounded-badge px-1.5 py-px text-xs font-semibold ${tone(kind, a.outcome)}`}
                  >
                    {OUTCOME[a.outcome] ?? a.outcome}
                  </span>
                </span>
                <span className="min-w-0">
                  <span className="text-text-secondary">{a.kind}</span>
                  {a.user ? (
                    <>
                      {" "}
                      by <EntityLink kind="user" value={a.user} className="font-mono" />
                    </>
                  ) : null}
                  {a.target ? (
                    <>
                      {" "}
                      on <EntityLink kind="host" value={a.target} className="font-mono" />
                    </>
                  ) : null}
                  <span
                    title={a.example}
                    className="mt-0.5 block truncate font-mono text-xs text-text-muted"
                  >
                    {a.example}
                  </span>
                </span>
                <span className="font-mono tabular-nums md:text-right">
                  {plural(a.events, "event", "events")}
                  <span className="block text-xs text-text-muted">
                    last <When iso={a.last} />
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => onSearch(a.search_sql)}
                  className="h-7 self-start rounded border border-border-strong px-2 text-sm hover:bg-surface-head"
                >
                  View in Search
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {hosts.length || users.length ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {[
            { title: kind === "ip" ? "Hosts targeted" : "Hosts", list: hosts, k: "host" as const },
            { title: kind === "ip" ? "Users tried" : "Users", list: users, k: "user" as const },
          ].map((col) =>
            col.list.length ? (
              <div key={col.k} className="rounded-card border border-border bg-surface">
                <h2 className="border-b border-border px-3 py-2 text-sm font-semibold">
                  {col.title} <span className="font-normal text-text-muted">{col.list.length}</span>
                </h2>
                <ul className="px-3 py-1 text-sm">
                  {col.list.slice(0, 10).map((t) => (
                    <li key={t.value} className="flex gap-2 py-0.5">
                      <EntityLink kind={col.k} value={t.value} className="min-w-0 font-mono" />
                      <span className="ml-auto font-mono tabular-nums text-text-secondary">
                        {n(t.events)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null,
          )}
        </div>
      ) : null}
      <div>
        <button
          type="button"
          onClick={() => onSearch(s.search_sql)}
          className="h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head"
        >
          View {s.events === 1 ? "the event" : `all ${n(s.events)} events`} in Search
        </button>
      </div>
    </section>
  );
}
