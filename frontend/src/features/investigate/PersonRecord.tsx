import { ChevronRight } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { EntityLink } from "@/components/EntityLink";
import { InlineError } from "@/components/InlineError";
import { PanelTitle } from "@/components/PanelTitle";
import { Skeleton } from "@/components/Skeleton";
import { StateNotice } from "@/components/StateNotice";
import { When } from "@/components/When";
import { ResultsTable } from "@/features/search/ResultsTable";
import {
  ApiError,
  api,
  type PersonM365List,
  type PersonRecordData,
  type PersonUsed,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { openDrill } from "@/lib/drill";
import { lastDays } from "@/lib/timeWindow";
import { useViewer } from "@/lib/viewer";
import { Activities, SignInSlices, finding } from "./EntitySummary";
import { PersonAiActivity } from "./PersonAiActivity";
import { PersonAlerts } from "./PersonLists";
import { Card } from "@/components/Card";
import { PersonTimeline } from "./PersonTimeline";

interface PersonRecordProps {
  person: string;
  /** The page's window: the summary and its numbers follow it exactly. */
  start: string | undefined;
  end?: string;
  /** The window's id, for caching: `start` moves with the clock. */
  range: string;
  /** "the last 7 days" */
  rangeWords: string;
  /** The window as whole days back from now, for the lists the server counts that way. */
  days: number;
  /** A link that names AI use scrolls to it. */
  toAi: boolean;
  onSearch: (sql: string) => void;
  /** The lane graph, drawn by the page; `onConnects` says when it is first opened. */
  connects: ReactNode;
  onConnects: () => void;
}

const n = (x: number) => x.toLocaleString();

function Kpi({
  label,
  value,
  onOpen,
  opens,
  context,
}: {
  label: string;
  value: ReactNode;
  onOpen?: () => void;
  opens?: string;
  /** The period, when it is not the page's Time ("Last 7 days"). */
  context?: string;
}) {
  return (
    <div data-kpi={label} className="flex min-w-0 flex-col gap-0.5 bg-surface px-3 py-2.5">
      <PanelTitle as="span">{label}</PanelTitle>
      {onOpen ? (
        <button
          type="button"
          onClick={onOpen}
          title={opens}
          className="self-start text-kpi tabular-nums hover:underline"
        >
          {value}
        </button>
      ) : (
        <span className="text-kpi tabular-nums">{value}</span>
      )}
      {context ? <span className="text-sm text-text-muted">{context}</span> : null}
    </div>
  );
}

/** The viewer's day as a window: local midnight to the next, cut to the page's own window,
 * so the first and last bars open exactly the rows they counted. */
function dayWindow(day: string, d: PersonRecordData): { from: string; to: string } {
  const from = new Date(`${day}T00:00:00`);
  const to = new Date(from);
  to.setDate(to.getDate() + 1);
  const lo = new Date(d.start);
  const hi = new Date(d.end);
  return {
    from: (from < lo ? lo : from).toISOString(),
    to: (to > hi ? hi : to).toISOString(),
  };
}

const DAY = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

/** Events per day as bars, failed sign-ins marked; a bar opens that day's events in Logs. */
function ActivityPerDay({
  person,
  days,
  d,
}: {
  person: string;
  days: number;
  d: PersonRecordData;
}) {
  const { canViewPeople = true } = useViewer();
  const who = canViewPeople ? person : "this person"; // D242: Logs names where it came from
  const top = Math.max(1, ...d.days.map((x) => x.events));
  const total = d.days.reduce((a, x) => a + x.events, 0);
  return (
    <Card title="Activity per day" note={`${n(total)} events, ${lastDays(days).toLowerCase()}`}>
      {total === 0 ? (
        <p className="px-3 py-4 text-sm text-text-secondary">No events in this range.</p>
      ) : (
        <ul aria-label="Events per day" className="flex h-28 items-end gap-1 px-3 pb-2 pt-3">
          {d.days.map((x) => {
            const label = DAY.format(new Date(`${x.day}T00:00:00`));
            const said = `${label}: ${n(x.events)} ${x.events === 1 ? "event" : "events"}${x.failed ? `, ${n(x.failed)} failed sign-ins` : ""}`;
            return (
              <li key={x.day} className="flex h-full min-w-0 flex-1 flex-col justify-end">
                <button
                  type="button"
                  disabled={!x.events}
                  aria-label={`${said}. Open in Logs`}
                  title={said}
                  onClick={() =>
                    openDrill({
                      sql: d.sql,
                      ...dayWindow(x.day, d),
                      origin: `${who} > Activity per day`,
                    })
                  }
                  className="group flex h-full w-full flex-col items-center justify-end"
                >
                  <span
                    aria-hidden
                    className="flex w-full max-w-5 flex-col justify-end overflow-hidden rounded-sm bg-text-secondary group-hover:bg-text group-disabled:bg-border"
                    style={{ height: `${x.events ? Math.max(4, (x.events / top) * 100) : 2}%` }}
                  >
                    {x.failed ? (
                      <span
                        className="w-full bg-warn"
                        style={{ height: `${Math.max(8, (x.failed / x.events) * 100)}%` }}
                      />
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <p className="flex justify-between border-t border-border px-3 py-1.5 text-xs text-text-muted">
        <span>{d.days[0] ? DAY.format(new Date(`${d.days[0].day}T00:00:00`)) : ""}</span>
        <span>Failed sign-ins are the marked part of a bar.</span>
        <span>
          {d.days.length ? DAY.format(new Date(`${d.days[d.days.length - 1]!.day}T00:00:00`)) : ""}
        </span>
      </p>
    </Card>
  );
}

const M365: [PersonM365List, string, string][] = [
  ["sign_ins", "Sign-ins", "sign-ins"],
  ["mail", "Mail", "mailbox rule changes"],
  ["admin", "Admin", "directory changes"],
];

/** The person's Microsoft 365 rows (ADR-0052): one table with a Sign-ins, Mail, Admin
 * switch. The server builds and runs each list with the viewer's own source access. */
function PersonM365({ person, days, d }: { person: string; days: number; d: PersonRecordData }) {
  const [list, setList] = useState<PersonM365List>("sign_ins");
  const { canViewPeople = true } = useViewer();
  const who = canViewPeople ? person : "this person"; // D242: Logs names where it came from
  const q = useQuery({
    queryKey: ["person-m365", person, list, days],
    queryFn: () => api.personM365(person, list, days),
  });
  const [, label, words] = M365.find(([id]) => id === list)!;
  const sql = d.m365_sql[list];
  return (
    <Card
      title="Microsoft 365"
      note={lastDays(days)}
      action={
        sql ? (
          <button
            type="button"
            onClick={() =>
              openDrill({ sql, from: d.start, to: d.end, origin: `${who} > ${label}` })
            }
            className="text-sm text-accent-text hover:underline"
          >
            Open in Logs
          </button>
        ) : null
      }
    >
      <div
        role="group"
        aria-label="Microsoft 365 list"
        className="flex border-b border-border px-3 py-2"
      >
        {M365.map(([id, name]) => (
          <button
            key={id}
            type="button"
            aria-pressed={list === id}
            onClick={() => setList(id)}
            className={cn(
              "h-7 border border-border-strong px-2.5 text-sm first:rounded-l last:rounded-r [&:not(:first-child)]:-ml-px",
              list === id ? "bg-accent-subtle font-semibold text-text" : "text-text-secondary",
            )}
          >
            {name}
          </button>
        ))}
      </div>
      {q.isLoading ? (
        <Skeleton label="this list" rows={3} className="rounded-none border-0" />
      ) : q.isError ? (
        <InlineError
          what={words}
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
        />
      ) : q.data && q.data.row_count === 0 ? (
        <p className="px-3 py-4 text-sm text-text-secondary">
          No Microsoft 365 {words} by this person in this range.
        </p>
      ) : q.data ? (
        // A section of the page, not the page: the list scrolls inside its own height.
        <div className="max-h-96 overflow-y-auto">
          <ResultsTable result={q.data} view="parsed" compact geo={q.data.geo} localTimes />
        </div>
      ) : null}
    </Card>
  );
}

/** Every device or address on the person's records (the server sends at most 100), with
 * events, failed sign-ins, and when it was last seen; the list scrolls inside its box. */
function UsedList({
  label,
  kind,
  rows,
}: {
  label: string;
  kind: "host" | "ip";
  rows: PersonUsed[];
}) {
  if (!rows.length)
    return <p className="px-3 py-3 text-sm text-text-secondary">None in this range.</p>;
  return (
    <div className="max-h-80 overflow-y-auto">
      <table aria-label={label} className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-text-secondary">
            <th className="px-3 py-1.5">{kind === "host" ? "Device" : "Address"}</th>
            <th className="px-2 py-1.5 text-right">Events</th>
            <th className="px-2 py-1.5 text-right">Failed</th>
            <th className="px-3 py-1.5">Last seen</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.value} className="border-b border-border last:border-0">
              <td className="px-3 py-1 font-mono [overflow-wrap:anywhere]">
                <EntityLink kind={kind} value={r.value} />
              </td>
              <td className="px-2 py-1 text-right font-mono tabular-nums">{n(r.events)}</td>
              <td
                className={cn(
                  "px-2 py-1 text-right font-mono tabular-nums",
                  r.failed ? "text-warn" : "text-text-muted",
                )}
              >
                {n(r.failed)}
              </td>
              <td className="whitespace-nowrap px-3 py-1 text-text-secondary">
                {r.last_seen ? <When iso={r.last_seen} /> : "·"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A part of the page that is read only when opened (the lanes, the timeline). */
function Fold({
  title,
  onOpen,
  children,
}: {
  title: string;
  onOpen?: () => void;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="overflow-hidden rounded-card border border-border bg-surface">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => {
          if (!open) onOpen?.();
          setOpen((v) => !v);
        }}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-semibold hover:bg-surface-head"
      >
        <ChevronRight size={14} aria-hidden className={cn(open && "rotate-90")} />
        {title}
      </button>
      {open ? <div className="border-t border-border">{children}</div> : null}
    </div>
  );
}

/** A person's page as a Record (ADR-0052, DESIGN.md 6.3): one sentence, a KPI row, then
 * Open alerts, Activity per day, Microsoft 365, and AI use in the main column, and Accounts,
 * Devices, and Addresses at the side. The timeline and the lanes are folded at the foot and
 * are read only when opened. */
export function PersonRecord({
  person,
  start,
  end,
  range,
  rangeWords,
  days,
  toAi,
  onSearch,
  connects,
  onConnects,
}: PersonRecordProps) {
  const { canViewPeople = true } = useViewer();
  const summary = useQuery({
    queryKey: ["entity-summary", "user", person, range],
    queryFn: () => api.entitySummary({ kind: "user", value: person, start, end }),
    staleTime: 60_000,
  });
  const record = useQuery({
    queryKey: ["person-record", person, days],
    queryFn: () => api.personRecord(person, days),
    staleTime: 60_000,
  });
  const used = useQuery({
    queryKey: ["person-hosts", person, days],
    queryFn: () => api.personHosts(person, days),
  });
  const alerts = useQuery({
    queryKey: ["person-alerts", person],
    queryFn: () => api.personAlerts(person),
  });
  const ai = useQuery({
    queryKey: ["person-ai", person, days],
    queryFn: () => api.personAi(person, days),
    enabled: canViewPeople,
    retry: false,
  });
  const aiBox = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (toAi) aiBox.current?.scrollIntoView?.({ block: "start" });
  }, [toAi, person]);

  const s = summary.data;
  const open = alerts.data?.items.filter((i) => i.state === "open").length;
  const wait = <span className="text-text-muted">·</span>;
  const allSignIns = s?.sign_in_slices?.find((x) => x.key === "all");
  const range7 = lastDays(days);
  // D242: only a refusal means hidden.
  const refused = ai.error instanceof ApiError && ai.error.status === 403;
  // The server sends at most 100 devices and 100 addresses.
  const count = (x: number) => (x >= 100 ? "100+" : n(x));
  return (
    <div className="flex flex-col gap-4">
      {!canViewPeople ? (
        // D242: without the permission the server sends no AI activity for a named person
        // and no names for Accounts; the title is masked too (owner, 2026-11-14).
        <StateNotice>
          Names are hidden: this person&apos;s name and AI activity are not shown. An admin can turn
          on View people in AI usage for you.
        </StateNotice>
      ) : null}
      <section aria-label="Summary" className="flex flex-col gap-3">
        {summary.isPending ? (
          <Skeleton label="the summary" block="h-6" />
        ) : summary.isError ? (
          <InlineError
            what="this person's summary"
            error={summary.error}
            onRetry={() => void summary.refetch()}
            retrying={summary.isFetching}
          />
        ) : (
          <p className="text-md">{finding(summary.data, rangeWords)}</p>
        )}
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-card border border-border bg-border md:grid-cols-5">
          <Kpi label="Open alerts" value={open === undefined ? wait : n(open)} />
          <Kpi
            label="Sign-ins"
            value={s ? n(s.sign_ins) : wait}
            onOpen={allSignIns?.count ? () => onSearch(allSignIns.search_sql) : undefined}
            opens="Open the sign-ins in Logs"
          />
          {/* These three count whole days back from now, whatever the page's Time: they say so. */}
          <Kpi
            label="Devices"
            value={used.data ? count(used.data.hosts.length) : wait}
            context={range7}
          />
          <Kpi
            label="Addresses"
            value={used.data ? count(used.data.addresses.length) : wait}
            context={range7}
          />
          <Kpi
            label="AI services"
            context={range7}
            value={
              !canViewPeople || refused ? (
                <span className="text-text-muted">Hidden</span>
              ) : ai.data ? (
                n(ai.data.services.length)
              ) : ai.isError ? (
                // Not loaded is not hidden: the AI use section below says what went wrong.
                <span className="text-text-muted">Not loaded</span>
              ) : (
                wait
              )
            }
          />
        </div>
        {s ? <SignInSlices s={s} onSearch={onSearch} /> : null}
      </section>
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="flex min-w-0 flex-col gap-4 lg:col-span-2">
          <PersonAlerts person={person} />
          {record.isPending ? (
            <Skeleton label="activity per day" rows={3} />
          ) : record.isError ? (
            <InlineError
              what="activity per day"
              error={record.error}
              onRetry={() => void record.refetch()}
              retrying={record.isFetching}
            />
          ) : (
            <>
              <ActivityPerDay person={person} days={days} d={record.data} />
              {record.data.m365 ? <PersonM365 person={person} days={days} d={record.data} /> : null}
            </>
          )}
          <div ref={aiBox} className="flex scroll-mt-4 flex-col gap-2">
            <h2 className="text-md font-semibold">AI use</h2>
            <PersonAiActivity person={person} days={days} />
          </div>
          {s ? <Activities s={s} kind="user" onSearch={onSearch} hideWho={!canViewPeople} /> : null}
          <Fold title="How it connects" onOpen={onConnects}>
            <section aria-label="Investigation graph" className="overflow-hidden bg-inset">
              {connects}
            </section>
          </Fold>
          <Fold title="Timeline">
            <PersonTimeline person={person} />
          </Fold>
        </div>
        <aside
          aria-label="Accounts, devices, and addresses"
          className="flex min-w-0 flex-col gap-4"
        >
          <Card title="Accounts" note="Names counted as this person">
            {record.isPending ? (
              <Skeleton label="accounts" rows={2} className="rounded-none border-0" />
            ) : record.data?.forms_hidden ? (
              // D242: the server sent how many names, not the names.
              <p className="px-3 py-3 text-sm text-text-muted">
                {record.data.forms_hidden === 1
                  ? "1 name hidden"
                  : `${n(record.data.forms_hidden)} names hidden`}
              </p>
            ) : record.data?.forms.length ? (
              <ul aria-label="Accounts" className="px-3 py-1 text-sm">
                {record.data.forms.map((f) => (
                  <li key={f} className="py-0.5 font-mono [overflow-wrap:anywhere]">
                    {f}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-3 py-3 text-sm text-text-secondary">None in this range.</p>
            )}
          </Card>
          {used.isLoading ? (
            <Skeleton label="devices and addresses" rows={4} />
          ) : used.isError || !used.data ? (
            <InlineError
              what="devices and addresses"
              error={used.error}
              onRetry={() => void used.refetch()}
              retrying={used.isFetching}
            />
          ) : (
            <>
              <Card title="Devices" note={range7}>
                <UsedList label="Devices" kind="host" rows={used.data.hosts} />
              </Card>
              <Card title="Addresses" note={range7}>
                <UsedList label="Addresses" kind="ip" rows={used.data.addresses} />
              </Card>
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
