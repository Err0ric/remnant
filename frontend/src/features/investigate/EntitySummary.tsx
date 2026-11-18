import { Card } from "@/components/Card";
import { PanelTitle } from "@/components/PanelTitle";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { EntityLink } from "@/components/EntityLink";
import { When } from "@/components/When";
import { ApiError, api, type EntitySummary as Summary } from "@/lib/api";
import { useSignInAbout } from "@/features/m365/signInCounting";
import { OutcomeBadge } from "@/features/audit/OutcomeBadge";
import { EmptyAddress } from "./EmptyAddress";
import { InventoryLine } from "./InventoryLine";

interface EntitySummaryProps {
  kind: "user" | "ip" | "host";
  value: string;
  start: string | undefined;
  /** The end of a Custom range; left out for a window that ends now. */
  end?: string;
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
  // On an address the cards below read more (DHCP names it in a line's text): say which.
  const which = s.kind === "ip" ? " with this address as source or destination" : "";
  return `${plural(s.events, "event", "events")}${which} from ${plural(s.sources.length, "source", "sources")} over ${rangeWords}.${where}`;
}

function Kpi({
  label,
  value,
  tone,
  small,
  title,
}: {
  label: string;
  value: ReactNode;
  tone?: string;
  small?: boolean;
  title?: string;
}) {
  return (
    <div
      title={title}
      className="flex min-w-0 flex-col gap-0.5 rounded-card border border-border bg-surface px-3 py-2"
    >
      <PanelTitle as="span">{label}</PanelTitle>
      <span
        className={`${small ? "text-base" : "text-lg"} font-semibold tabular-nums [overflow-wrap:anywhere] ${tone ?? ""}`}
      >
        {value}
      </span>
    </div>
  );
}

// The app's one outcome mapping (OutcomeBadge), as the address page's access card has it.
const OUTCOME: Record<string, [string, string]> = {
  succeeded: ["success", "Succeeded"],
  failed: ["failure", "Failed"],
  allowed: ["success", "Allowed"],
  denied: ["denied", "Denied"],
  not_counted: ["other", "Interrupted or expired"],
  signed_out: ["other", "Signed out"],
  other: ["other", "Other"],
};

/** This entity's sign-ins by outcome (D158): real failures, interrupted, expired, other,
 * and all, each one click from its rows in Logs. Shown only when there are sign-ins. */
export function SignInSlices({ s, onSearch }: { s: Summary; onSearch: (sql: string) => void }) {
  const about = useSignInAbout();
  const slices = s.sign_in_slices ?? [];
  if (!slices.some((x) => x.key === "all" && x.count > 0)) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-text-secondary">Sign-ins</span>
      <div
        role="group"
        aria-label="Sign-ins by outcome"
        className="flex flex-wrap rounded border border-border"
      >
        {slices.map((x) => (
          <button
            key={x.key}
            type="button"
            onClick={() => onSearch(x.search_sql)}
            title={`Open ${x.count.toLocaleString()} ${x.key === "all" ? "sign-ins" : x.label.toLowerCase()} in Logs`}
            className="flex h-7 items-center gap-1.5 border-r border-border px-2.5 last:border-r-0 hover:bg-surface-head"
          >
            {x.label}
            <span className="font-mono tabular-nums text-text-muted">
              {x.count.toLocaleString()}
            </span>
          </button>
        ))}
      </div>
      <span
        role="img"
        aria-label={`How this is counted: ${about}`}
        title={`How this is counted: ${about}`}
        className="flex size-3.5 shrink-0 cursor-help items-center justify-center rounded-full border border-text-muted text-[10px] font-semibold leading-none text-text-muted"
      >
        i
      </span>
    </div>
  );
}

/** What the entity did, grouped by outcome, each with a real line and its rows in Logs. */
export function Activities({
  s,
  onSearch,
  hideWho = false,
}: {
  s: Summary;
  /** Which page it is on; outcomes look the same on every page (one mapping). */
  kind?: "user" | "ip" | "host";
  onSearch: (sql: string) => void;
  /** Names hidden on a person's page (D242): the "by <name>" label, which repeats the
   * names counted as the person, is left out. */
  hideWho?: boolean;
}) {
  if (!s.activities.length) return null;
  return (
    <Card title="What it did" note="by outcome">
      <ul aria-label="Activities">
        {s.activities.map((a, i) => (
          <li
            key={i}
            className="grid grid-cols-1 gap-x-3 gap-y-1 border-b border-border px-3 py-2 text-sm last:border-0 md:grid-cols-[6rem_minmax(0,1fr)_auto_auto]"
          >
            <span>
              <OutcomeBadge
                outcome={(OUTCOME[a.outcome] ?? ["other"])[0]}
                label={(OUTCOME[a.outcome] ?? ["", a.outcome])[1]}
              />
            </span>
            <span className="min-w-0">
              <span className="text-text-secondary">{a.kind}</span>
              {a.user && !hideWho ? (
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
            <span className="whitespace-nowrap font-mono tabular-nums md:text-right">
              {plural(a.events, "event", "events")}
              <span className="block whitespace-nowrap text-xs text-text-muted">
                last <When iso={a.last} />
              </span>
            </span>
            <button
              type="button"
              onClick={() => onSearch(a.search_sql)}
              className="h-7 self-start rounded border border-border-strong px-2 text-sm hover:bg-surface-head"
            >
              View in Logs
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** The top of an entity's page (DESIGN 6.2): the finding, KPI cards, activities grouped by
 * outcome with a real line each, and what it touched. Every value is a pivot link. */
export function EntitySummary({
  kind,
  value,
  start,
  end,
  range,
  rangeWords,
  onSearch,
}: EntitySummaryProps) {
  const q = useQuery({
    queryKey: ["entity-summary", kind, value, range],
    queryFn: () => api.entitySummary({ kind, value, start, end }),
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
            // The one place a success from an address is marked: badges stay neutral.
            tone={s.succeeded ? "text-warn" : ""}
            title="Sign-ins that succeeded from this address"
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
      <p className="text-md">
        {finding(s, rangeWords)}
        {/* At the top with the answer, so the page does not seem to end below. Not at 0:
            an empty search is no control. */}
        {s.events ? (
          <>
            {" "}
            <button
              type="button"
              onClick={() => onSearch(s.search_sql)}
              className="text-sm text-accent-text hover:underline"
            >
              View {s.events === 1 ? "the event" : `all ${n(s.events)} events`} in Logs
            </button>
          </>
        ) : null}
      </p>
      {kind !== "user" ? <InventoryLine value={value} start={start} end={end} /> : null}
      {kind === "ip" && !s.events ? (
        // The finding above already says there is nothing: no second headline.
        <EmptyAddress value={value} start={start} end={end} rangeWords={rangeWords} noHeadline />
      ) : null}
      {s.events ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {kpis}
          {/* An address's sections read more than these events (DHCP names it in a line's
            text): its times say they are of these events. */}
          <Kpi
            label={kind === "ip" ? "First event" : "First seen"}
            small
            value={<When iso={s.first_seen} />}
          />
          <Kpi
            label={kind === "ip" ? "Last event" : "Last seen"}
            small
            value={<When iso={s.last_seen} />}
          />
          {kind === "ip" && s.geo ? (
            <Kpi
              label="Country and network"
              value={`${s.geo.country ?? "?"}${s.geo.asn ? ` · AS${s.geo.asn}` : ""}`}
            />
          ) : null}
        </div>
      ) : null}
      <SignInSlices s={s} onSearch={onSearch} />
      <Activities s={s} kind={kind} onSearch={onSearch} />
      {hosts.length || users.length ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {[
            { title: kind === "ip" ? "Hosts targeted" : "Hosts", list: hosts, k: "host" as const },
            { title: kind === "ip" ? "Users tried" : "Users", list: users, k: "user" as const },
          ].map((col) =>
            col.list.length ? (
              <Card key={col.k} title={col.title} note={col.list.length.toLocaleString()}>
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
              </Card>
            ) : null,
          )}
        </div>
      ) : null}
    </section>
  );
}
