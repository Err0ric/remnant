import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { LoadFailed } from "@/components/LoadFailed";
import { EntityLink } from "@/components/EntityLink";
import { api, type TimelineRow } from "@/lib/api";
import { cn } from "@/lib/cn";
import { openDrill } from "@/lib/drill";
import { navigate } from "@/lib/route";
import { useViewer } from "@/lib/viewer";

const KIND: Record<string, string> = {
  signin: "Sign-in",
  session: "Claude session",
  ai_first: "AI use",
  consent: "App consent",
  audit: "Microsoft 365",
  events: "Events",
  alert: "Alert",
};
const DAYS = [1, 7, 30] as const;

function day(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** A person's timeline (ADR-0038 section 9): one row per action across sources, newest
 * first, grouped by day; each row opens its own events in Search. */
export function PersonTimeline({ person }: { person: string }) {
  const [days, setDays] = useState<(typeof DAYS)[number]>(7);
  const q = useQuery({
    queryKey: ["person-timeline", person, days],
    queryFn: () => api.personTimeline(person, days),
  });
  const d = q.data;
  const groups = new Map<string, TimelineRow[]>();
  for (const r of d?.rows ?? []) {
    const k = r.start.slice(0, 10);
    groups.set(k, [...(groups.get(k) ?? []), r]);
  }
  const open = (r: TimelineRow) =>
    r.item_id
      ? () => navigate("alerts", `item=${r.item_id}`)
      : r.sql
        ? () => openDrill({ sql: r.sql, from: r.start, to: r.end, origin: `${person} > Timeline` })
        : undefined;
  return (
    <section
      aria-label="Timeline"
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border bg-surface-head px-3 py-2">
        <h2 className="text-base font-semibold">Timeline</h2>
        <div role="group" aria-label="Time window" className="flex rounded border border-border">
          {DAYS.map((n) => (
            <button
              key={n}
              type="button"
              aria-pressed={n === days}
              onClick={() => setDays(n)}
              className={cn(
                "h-7 px-2.5 text-sm first:rounded-l last:rounded-r",
                n === days
                  ? "bg-surface font-semibold text-text"
                  : "text-text-secondary hover:text-text",
              )}
            >
              {n === 1 ? "24 hours" : `${n} days`}
            </button>
          ))}
        </div>
        {d ? (
          <button
            type="button"
            onClick={() =>
              openDrill({ sql: d.sql, from: d.start, to: d.end, origin: `${person} > Timeline` })
            }
            className="ml-auto text-sm text-accent-text hover:underline"
          >
            Open in Search
          </button>
        ) : null}
      </div>
      {d?.maybe?.length ? <MaybeSame person={d.person} maybe={d.maybe} /> : null}
      {d && (d.forms.length || d.devices.length) ? (
        <p className="border-b border-border px-3 py-2 text-sm text-text-secondary">
          {d.forms.length ? (
            <>
              Seen as <span className="font-mono text-text">{d.forms.join(", ")}</span>.{" "}
            </>
          ) : null}
          {d.devices.length ? (
            <>
              Devices:{" "}
              {d.devices.map((h, i) => (
                <span key={h} className="font-mono">
                  {i ? ", " : ""}
                  <EntityLink kind="host" value={h} />
                </span>
              ))}
              .
            </>
          ) : null}
        </p>
      ) : null}
      {q.isLoading ? (
        <div aria-busy="true" className="h-40 animate-pulse" />
      ) : q.isError ? (
        <LoadFailed
          what="the timeline"
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
        />
      ) : d && d.rows.length === 0 ? (
        <p className="px-3 py-4 text-sm text-text-secondary">
          No activity by this person in this window, in the sources you can read.
        </p>
      ) : d ? (
        <ol aria-label="Activity by day" className="flex flex-col">
          {[...groups.entries()].map(([k, rows]) => (
            <li key={k}>
              <h3 className="border-b border-border bg-surface-head px-3 py-1 text-sm font-semibold">
                {day(`${k}T00:00:00Z`)}
              </h3>
              <ul className="flex flex-col">
                {rows.map((r, i) => {
                  const go = open(r);
                  return (
                    <li
                      key={`${r.kind}:${r.start}:${i}`}
                      data-row={r.kind}
                      className="grid grid-cols-[4.5rem_8rem_minmax(0,1fr)_auto] items-baseline gap-x-3 border-b border-border px-3 py-1 text-sm last:border-0"
                    >
                      <time dateTime={r.start} className="font-mono tabular-nums text-text-muted">
                        {r.start.slice(11, 16)}
                      </time>
                      <span className="text-text-secondary">{KIND[r.kind] ?? r.kind}</span>
                      <span className={cn("min-w-0 truncate", r.tone === "warn" && "text-warn")}>
                        {go ? (
                          <button
                            type="button"
                            data-drill=""
                            onClick={go}
                            title={
                              r.item_id
                                ? "Open the alert"
                                : `Open ${r.count.toLocaleString()} events in Search`
                            }
                            className="max-w-full truncate text-left hover:underline"
                          >
                            {r.title}
                          </button>
                        ) : (
                          r.title
                        )}
                        <span className="ml-2 text-text-muted">{r.detail}</span>
                      </span>
                      <span className="font-mono tabular-nums text-text-muted">
                        {r.count > 1 ? `×${r.count.toLocaleString()}` : ""}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ol>
      ) : null}
      {d?.more ? (
        <p className="border-t border-border px-3 py-2 text-sm text-text-muted">
          The newest 500 rows. Narrow the window, or open the rest in Search.
        </p>
      ) : null}
    </section>
  );
}

/** Names on this person's devices that look like the same person ("robin" beside
 * "robin.okafor@example.com"). Administrators make one an alias (ADR-0018); others see
 * the hint only. */
function MaybeSame({
  person,
  maybe,
}: {
  person: string;
  maybe: { name: string; devices: string[] }[];
}) {
  const { isAdmin } = useViewer();
  const client = useQueryClient();
  const merge = useMutation({
    mutationFn: (alias: string) => api.setIdentityAlias(alias, person),
    onSuccess: () => void client.invalidateQueries(),
  });
  return (
    <p className="border-b border-border px-3 py-2 text-sm text-text-secondary">
      Possibly the same person:{" "}
      {maybe.map((m, i) => (
        <span key={m.name}>
          {i ? "; " : ""}
          <span className="font-mono text-text">{m.name}</span> (on {m.devices.join(", ")})
          {isAdmin ? (
            <>
              {" "}
              <button
                type="button"
                disabled={merge.isPending}
                onClick={() => merge.mutate(m.name)}
                className="text-accent-text hover:underline"
              >
                Make {m.name} an alias
              </button>
            </>
          ) : null}
        </span>
      ))}
      .{!isAdmin ? " An administrator can make a name an alias on Settings > Identities." : ""}
    </p>
  );
}
