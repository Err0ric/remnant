import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";
import { api, type Cell, type M365Overview, type QueryResult } from "@/lib/api";
import { cn } from "@/lib/cn";
import { drillSql, openDrill } from "@/lib/drill";
import { LoadFailed } from "@/components/LoadFailed";
import { When } from "@/components/When";

const TITLE = "Admin changes";
const ORIGIN = `Microsoft 365 > ${TITLE}`;
// Most a provisioning group lists when opened; the rest are one click away in Search.
const MAX_CYCLES = 200;

export interface Change {
  time: string;
  actor: string;
  actorKind: "app" | "person";
  appId: string | null;
  operation: string;
  target: string | null;
  status: "Success" | "Failure";
  events: number;
  eventIds: string[];
  changed: string;
  provisioning: boolean;
  service: string;
  rank: number;
}

export interface CycleGroup {
  key: string;
  service: string;
  /** The viewer's date, "Oct 30". */
  day: string;
  cycles: Change[];
  failed: number;
}

function text(c: Cell | undefined): string {
  return c === null || c === undefined ? "" : String(c);
}

/** The Admin query's rows as changes. */
export function changes(result: QueryResult): Change[] {
  const at = (c: string) => result.columns.indexOf(c);
  return result.rows.map((r) => ({
    time: text(r[at("time")]),
    actor: text(r[at("actor")]) || "(unknown)",
    actorKind: r[at("actor_kind")] === "app" ? "app" : "person",
    appId: text(r[at("app_id")]) || null,
    operation: text(r[at("operation")]),
    target: text(r[at("target")]) || null,
    status: r[at("status")] === "Failure" ? "Failure" : "Success",
    events: Number(r[at("events")] ?? 0),
    eventIds: Array.isArray(r[at("event_ids")]) ? (r[at("event_ids")] as Cell[]).map(text) : [],
    changed: text(r[at("changed")]),
    provisioning: r[at("provisioning")] === true,
    service: text(r[at("service")]) || text(r[at("actor")]),
    rank: Number(r[at("rank")] ?? 0),
  }));
}

function localDay(iso: string, timeZone?: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone });
}

/** Sync and provisioning cycles per service and viewer day, failed cycles kept apart. */
export function cycleGroups(
  rows: Change[],
  timeZone?: string,
): { groups: CycleGroup[]; failed: Change[] } {
  const groups = new Map<string, CycleGroup>();
  const failed: Change[] = [];
  for (const c of rows) {
    if (!c.provisioning) continue;
    if (c.status === "Failure") failed.push(c);
    const day = localDay(c.time, timeZone);
    const key = `${c.service}|${day}`;
    const g = groups.get(key) ?? { key, service: c.service, day, cycles: [], failed: 0 };
    g.cycles.push(c);
    if (c.status === "Failure") g.failed += 1;
    groups.set(key, g);
  }
  const list = [...groups.values()].sort(
    (a, b) =>
      (b.cycles[0]?.time ?? "").localeCompare(a.cycles[0]?.time ?? "") ||
      a.service.localeCompare(b.service),
  );
  return { groups: list, failed };
}

/** "Example Directory Sync: 288 cycles, all succeeded" or "...: 288 cycles, 1 failed". */
export function cycleLine(g: CycleGroup): string {
  const n = g.cycles.length;
  const outcome = g.failed ? `${g.failed} failed` : "all succeeded";
  return `${g.service}: ${n.toLocaleString()} ${n === 1 ? "cycle" : "cycles"}, ${outcome}`;
}

function eventsSql(ids: string[]): string {
  const list = ids.map((id) => `'${id.replaceAll("'", "''")}'`).join(", ");
  return `SELECT * FROM events WHERE event_id IN (${list}) ORDER BY time`;
}

interface RowProps {
  c: Change;
  m: M365Overview;
  timeZone?: string;
}

function ChangeRow({ c, m, timeZone }: RowProps) {
  const [open, setOpen] = useState(false);
  return (
    <Fragment>
      <tr className="border-b border-border align-top">
        <td className="px-2 py-1.5">
          <button
            type="button"
            aria-expanded={open}
            aria-label={open ? "Hide details" : "Show details"}
            onClick={() => setOpen(!open)}
            className="text-text-muted hover:text-text"
          >
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        </td>
        <td className="whitespace-nowrap px-2 py-1.5">
          <When iso={c.time} timeZone={timeZone} />
        </td>
        <td className="min-w-0 px-2 py-1.5">
          <span className="font-mono">{c.actor}</span>
          {c.actorKind === "app" ? (
            <span className="ml-1.5 rounded-badge bg-sev-info-bg px-1.5 py-px text-xs text-sev-info-text">
              App
            </span>
          ) : null}
        </td>
        <td className="px-2 py-1.5">
          {c.operation}
          {c.rank === 0 ? <span className="ml-1.5 text-xs text-text-muted">routine</span> : null}
        </td>
        <td className="min-w-0 px-2 py-1.5 font-mono">{c.target ?? "·"}</td>
        <td className="px-2 py-1.5">
          <span className={c.status === "Failure" ? "text-danger" : "text-text-secondary"}>
            {c.status}
          </span>
        </td>
        <td className="min-w-0 px-2 py-1.5 font-mono text-text-secondary">{c.changed || "·"}</td>
        <td className="px-2 py-1.5 text-right">
          <button
            type="button"
            title={`Open ${c.events.toLocaleString()} events in Search`}
            onClick={() =>
              openDrill({ sql: eventsSql(c.eventIds), from: m.start, to: m.end, origin: ORIGIN })
            }
            className="font-mono tabular-nums text-accent-text hover:underline"
          >
            {c.events.toLocaleString()}
          </button>
        </td>
      </tr>
      {open ? (
        <tr className="border-b border-border bg-surface-head">
          <td />
          <td colSpan={7} className="px-2 py-1.5 text-sm text-text-secondary">
            {c.appId ? (
              <div>
                App id: <span className="font-mono">{c.appId}</span>
              </div>
            ) : null}
            <div>
              Event ids: <span className="font-mono break-all">{c.eventIds.join(", ")}</span>
            </div>
          </td>
        </tr>
      ) : null}
    </Fragment>
  );
}

function ChangeTable({
  rows,
  m,
  label,
  timeZone,
}: {
  rows: Change[];
  m: M365Overview;
  label: string;
  timeZone?: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" aria-label={label}>
        <thead>
          <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
            <th className="w-6 px-2 py-1.5" />
            <th className="px-2 py-1.5 font-semibold">Time</th>
            <th className="px-2 py-1.5 font-semibold">Who</th>
            <th className="px-2 py-1.5 font-semibold">Operation</th>
            <th className="px-2 py-1.5 font-semibold">Target</th>
            <th className="px-2 py-1.5 font-semibold">Status</th>
            <th className="px-2 py-1.5 font-semibold">Changed</th>
            <th className="px-2 py-1.5 text-right font-semibold">Events</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <ChangeRow
              key={`${c.time}|${c.eventIds[0] ?? c.operation}`}
              c={c}
              m={m}
              timeZone={timeZone}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Microsoft 365 > Admin (owner, 2026-11-01): admin changes by people and apps, real
 * changes first and routine updates hidden by default, with sync and provisioning cycles
 * grouped per service and day underneath. */
export function AdminChanges({ m, timeZone }: { m: M365Overview; timeZone?: string }) {
  const sql = m.lists.admin;
  const filled = drillSql({ sql, from: m.start, to: m.end });
  const q = useQuery<QueryResult>({
    queryKey: ["m365-list", filled],
    queryFn: () => api.query({ sql: filled, start: m.start, end: m.end }),
  });
  const [hideRoutine, setHideRoutine] = useState(true);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const all = q.data ? changes(q.data) : [];
  const real = all.filter((c) => !c.provisioning);
  const routine = real.filter((c) => c.rank === 0).length;
  const shown = hideRoutine ? real.filter((c) => c.rank > 0) : real;
  const { groups, failed } = cycleGroups(all, timeZone);
  return (
    <section aria-label={TITLE} className="rounded-card border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-3 py-2">
        <h2 className="text-base font-semibold">{TITLE}</h2>
        {q.data ? (
          <span className="text-sm text-text-muted">
            {real.length.toLocaleString()} by people and apps, {routine.toLocaleString()} routine
            {q.data.truncated ? " (first rows only)" : ""}
          </span>
        ) : null}
        <label className="ml-auto flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={hideRoutine}
            onChange={(e) => setHideRoutine(e.target.checked)}
          />
          Hide routine
        </label>
        <button
          type="button"
          onClick={() => openDrill({ sql, from: m.start, to: m.end, origin: ORIGIN })}
          className="text-sm text-accent-text hover:underline"
        >
          Open in Search
        </button>
      </div>
      <p className="border-b border-border px-3 py-1.5 text-sm text-text-secondary">
        Role, policy, credential, and user create, delete, or disable changes come first. Routine
        updates (a user&apos;s or group&apos;s details) are hidden unless you show them.
      </p>
      {q.isLoading ? (
        <div aria-busy="true" className="h-40 animate-pulse bg-surface" />
      ) : q.isError ? (
        <LoadFailed
          what={TITLE}
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
        />
      ) : (
        <>
          {shown.length ? (
            <ChangeTable rows={shown} m={m} label={TITLE} timeZone={timeZone} />
          ) : (
            <p className="p-3 text-sm text-text-secondary">
              {real.length
                ? `No changes beyond routine updates. ${routine.toLocaleString()} routine hidden.`
                : "No admin changes by people or apps in this window."}
            </p>
          )}
          <section aria-label="Provisioning" className="border-t border-border">
            <h3 className="px-3 py-2 text-sm font-semibold">Provisioning</h3>
            {failed.length ? (
              <ChangeTable rows={failed} m={m} label="Failed cycles" timeZone={timeZone} />
            ) : null}
            {groups.length ? (
              <ul aria-label="Cycles by service and day">
                {groups.map((g) => {
                  const isOpen = open.has(g.key);
                  return (
                    <li key={g.key} className="border-t border-border">
                      <button
                        type="button"
                        aria-expanded={isOpen}
                        onClick={() => {
                          const next = new Set(open);
                          if (isOpen) next.delete(g.key);
                          else next.add(g.key);
                          setOpen(next);
                        }}
                        className="flex w-full items-baseline gap-2 px-3 py-2 text-left text-sm hover:bg-row-selected"
                      >
                        <span aria-hidden className="self-center text-text-muted">
                          {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </span>
                        <span className="text-text-muted">{g.day}</span>
                        <span className={cn(g.failed ? "text-danger" : "")}>{cycleLine(g)}</span>
                      </button>
                      {isOpen ? (
                        <ChangeTable
                          rows={g.cycles.slice(0, MAX_CYCLES)}
                          m={m}
                          label={`${g.service} cycles, ${g.day}`}
                          timeZone={timeZone}
                        />
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="px-3 pb-2 text-sm text-text-secondary">
                No sync or provisioning cycles in this window.
              </p>
            )}
          </section>
        </>
      )}
    </section>
  );
}
