import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { api, type Cell, type M365Overview, type QueryResult } from "@/lib/api";
import { cn } from "@/lib/cn";
import { drillSql, openDrill } from "@/lib/drill";
import { LoadFailed } from "@/components/LoadFailed";
import { ResultsTable } from "@/features/search/ResultsTable";

const TITLE = "Inbox rules and forwarding";
// Shown inside a burst: who and which burst are its heading already.
const HIDDEN = ["person", "burst", "risky", "operation"];
const CLASS_WORD: Record<string, string> = {
  organizing: "organizing",
  hiding: "hiding",
  deleting: "deleting",
  forwarding: "forwarding",
  other: "other",
};
const RANK: Record<string, number> = { high: 3, medium: 2, low: 1 };
const TONE: Record<string, string> = {
  high: "bg-sev-high-bg text-sev-high-text",
  medium: "bg-sev-medium-bg text-sev-medium-text",
};

export interface Burst {
  key: string;
  person: string;
  first: string;
  last: string;
  rows: Cell[][];
  classes: [string, number][];
  risky: number;
  severity: string;
}

function day(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** "dana@example.com created 62 rules Oct 29 to 30: 60 organizing, 2 hiding". */
export function burstLine(b: Burst): string {
  const n = b.rows.length;
  const span = day(b.first) === day(b.last) ? day(b.first) : `${day(b.first)} to ${day(b.last)}`;
  const parts = b.classes.map(([c, k]) => `${k} ${CLASS_WORD[c] ?? c}`).join(", ");
  return `${b.person} created ${n} ${n === 1 ? "rule" : "rules"} ${span}: ${parts}`;
}

/** Rules grouped by person and burst (no gap over 24 hours), risky bursts first. */
export function bursts(result: QueryResult): Burst[] {
  const at = (c: string) => result.columns.indexOf(c);
  const [iBurst, iPerson, iTime, iClass, iRisky, iSev] = [
    "burst",
    "person",
    "time",
    "class",
    "risky",
    "severity",
  ].map(at) as [number, number, number, number, number, number];
  const groups = new Map<string, Cell[][]>();
  for (const row of result.rows) {
    const k = String(row[iBurst]);
    groups.set(k, [...(groups.get(k) ?? []), row]);
  }
  const out: Burst[] = [];
  for (const [key, rows] of groups) {
    const times = rows.map((r) => String(r[iTime])).sort();
    const count = new Map<string, number>();
    for (const r of rows) count.set(String(r[iClass]), (count.get(String(r[iClass])) ?? 0) + 1);
    const sev = rows
      .map((r) => String(r[iSev]))
      .reduce((a, b) => ((RANK[b] ?? 0) > (RANK[a] ?? 0) ? b : a), "low");
    out.push({
      key,
      person: String(rows[0]![iPerson] ?? "(no user)"),
      first: times[0]!,
      last: times[times.length - 1]!,
      rows,
      classes: [...count.entries()].sort((a, b) => b[1] - a[1]),
      risky: rows.filter((r) => r[iRisky] === true).length,
      severity: sev,
    });
  }
  return out.sort(
    (a, b) =>
      (RANK[b.severity] ?? 0) - (RANK[a.severity] ?? 0) ||
      b.risky - a.risky ||
      b.last.localeCompare(a.last),
  );
}

/** Microsoft 365 > Mail (owner, 2026-10-31; D132): each rule's settings and class, a burst of
 * one person's rules as one row with the list underneath. Only hiding, deleting, and
 * external forwarding are risky. */
export function MailRules({ m }: { m: M365Overview }) {
  const sql = m.lists.mail;
  const filled = drillSql({ sql, from: m.start, to: m.end });
  const q = useQuery<QueryResult>({
    queryKey: ["m365-list", filled],
    queryFn: () => api.query({ sql: filled, start: m.start, end: m.end }),
  });
  const [open, setOpen] = useState<Set<string>>(new Set());
  const groups = q.data ? bursts(q.data) : [];
  return (
    <section aria-label={TITLE} className="rounded-card border border-border bg-surface">
      <div className="flex items-center gap-3 border-b border-border px-3 py-2">
        <h2 className="text-base font-semibold">{TITLE}</h2>
        {q.data ? (
          <span className="text-sm text-text-muted">
            {q.data.row_count.toLocaleString()} {q.data.row_count === 1 ? "rule" : "rules"}
            {q.data.truncated ? "+" : ""}, risky first
          </span>
        ) : null}
        <button
          type="button"
          onClick={() =>
            openDrill({ sql, from: m.start, to: m.end, origin: `Microsoft 365 > ${TITLE}` })
          }
          className="ml-auto text-sm text-accent-text hover:underline"
        >
          Open in Search
        </button>
      </div>
      <p className="border-b border-border px-3 py-1.5 text-sm text-text-secondary">
        Risky: rules that hide mail (Junk, RSS Feeds, Archive, Conversation History, Deleted Items,
        or mark read and move), delete it, or forward it outside the person&apos;s domain. Rules
        that file mail into other folders are organizing.
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
      ) : q.data && !groups.length ? (
        <p className="p-3 text-sm text-text-secondary">No inbox rules in this window.</p>
      ) : (
        <ul aria-label="Rule bursts">
          {groups.map((b) => {
            const isOpen = open.has(b.key);
            return (
              <li key={b.key} className="border-b border-border last:border-0">
                <button
                  type="button"
                  aria-expanded={isOpen}
                  onClick={() => {
                    const next = new Set(open);
                    if (isOpen) next.delete(b.key);
                    else next.add(b.key);
                    setOpen(next);
                  }}
                  className="flex w-full items-baseline gap-2 px-3 py-2 text-left text-sm hover:bg-row-selected"
                >
                  <span aria-hidden className="self-center text-text-muted">
                    {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </span>
                  {b.risky ? (
                    <span
                      className={cn(
                        "rounded-badge px-2 py-px text-xs",
                        TONE[b.severity] ?? TONE.medium,
                      )}
                    >
                      {b.risky} risky
                    </span>
                  ) : null}
                  <span>{burstLine(b)}</span>
                </button>
                {isOpen && q.data ? (
                  <ResultsTable
                    result={{ ...q.data, rows: b.rows, row_count: b.rows.length, truncated: false }}
                    view="parsed"
                    compact
                    hidden={HIDDEN}
                  />
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
