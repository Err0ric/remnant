import { useState } from "react";
import { EntityLink } from "@/components/EntityLink";
import type { Cell, QueryResult } from "@/lib/api";
import { kindForColumn } from "@/lib/entity";

const FIRST = 50;

function text(v: Cell): string {
  if (v === null || v === undefined) return "";
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}

/** An Ask turn's rows (ADR-0042 row 16): monospace, people, addresses, hosts, and services
 * as links to their pages, the first 50 with the rest one click away. Log values are text
 * nodes only. */
interface AskResultsProps {
  result: QueryResult;
  /** Group keys (D173): each row gets "Show events" when there are any. */
  drillKeys?: string[];
  onShowEvents?: (values: Record<string, Cell>) => void;
}

export function AskResults({ result, drillKeys = [], onShowEvents }: AskResultsProps) {
  const [all, setAll] = useState(false);
  const rows = all ? result.rows : result.rows.slice(0, FIRST);
  const kinds = result.columns.map((c) => kindForColumn(c));
  const drill = onShowEvents && drillKeys.length > 0;
  const keyAt = drillKeys.map((k) => result.columns.indexOf(k));
  const valuesOf = (r: Cell[]) =>
    Object.fromEntries(drillKeys.map((k, i): [string, Cell] => [k, r[keyAt[i]!] ?? null]));
  if (result.rows.length === 0)
    return <p className="text-sm text-text-secondary">No rows matched in this time range.</p>;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="overflow-x-auto rounded border border-border">
        <table aria-label="Results" className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
              {result.columns.map((c) => (
                <th key={c} className="whitespace-nowrap px-2.5 py-1.5 font-mono font-semibold">
                  {c}
                </th>
              ))}
              {drill ? (
                <th className="px-2.5 py-1.5">
                  <span className="sr-only">Events</span>
                </th>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-border last:border-0">
                {r.map((v, j) => {
                  const kind = kinds[j];
                  return (
                    <td key={j} className="max-w-96 px-2.5 py-1 align-top font-mono">
                      {kind ? <EntityLink kind={kind} value={v} /> : text(v)}
                    </td>
                  );
                })}
                {drill ? (
                  <td className="whitespace-nowrap px-2.5 py-1 text-right align-top">
                    <button
                      type="button"
                      aria-label={`Show events for ${drillKeys.map((k, n) => `${k} ${text(r[keyAt[n]!] ?? null) || "none"}`).join(", ")}`}
                      onClick={() => onShowEvents(valuesOf(r))}
                      className="text-accent-text hover:underline"
                    >
                      Show events
                    </button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm text-text-muted">
        <span className="tabular-nums">
          {result.row_count.toLocaleString()} {result.row_count === 1 ? "row" : "rows"}
          {result.truncated ? " (the first 1,000; open in SQL to see more)" : ""}
        </span>
        {!all && result.rows.length > FIRST ? (
          <button
            type="button"
            onClick={() => setAll(true)}
            className="text-accent-text hover:underline"
          >
            Show all {result.rows.length.toLocaleString()}
          </button>
        ) : null}
      </div>
    </div>
  );
}
