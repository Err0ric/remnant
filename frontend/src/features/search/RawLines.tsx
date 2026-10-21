import { useQuery } from "@tanstack/react-query";
import { api, type QueryResult } from "@/lib/api";
import { rawSql } from "@/lib/search";

interface RawLinesProps {
  result: QueryResult;
  rows: QueryResult["rows"];
}

/**
 * The page's events exactly as received. Uses the `raw` column when the query selected it,
 * otherwise looks the lines up by event_id. Always rendered as text, never as markup.
 */
export function RawLines({ result, rows }: RawLinesProps) {
  const rawIndex = result.columns.indexOf("raw");
  const idIndex = result.columns.indexOf("event_id");
  const ids = idIndex >= 0 ? rows.map((r) => String(r[idIndex] ?? "")) : [];
  const sql = rawIndex < 0 ? rawSql(ids) : null;
  const lookup = useQuery({
    queryKey: ["raw-lines", sql],
    queryFn: () => api.query({ sql: sql ?? "" }),
    enabled: sql !== null,
  });

  if (rawIndex < 0 && idIndex < 0) {
    return (
      <p className="px-3.5 py-6 text-sm text-text-secondary">
        Raw view needs <span className="font-mono">event_id</span> or{" "}
        <span className="font-mono">raw</span> in the query&apos;s columns. Aggregates have no raw
        lines.
      </p>
    );
  }

  let lines: string[];
  if (rawIndex >= 0) {
    lines = rows.map((r) => String(r[rawIndex] ?? ""));
  } else {
    const byId = new Map((lookup.data?.rows ?? []).map((r) => [String(r[0]), String(r[1] ?? "")]));
    lines = ids.map((id) => byId.get(id) ?? (lookup.isPending ? "…" : ""));
  }

  return (
    <ol aria-label="Raw events" className="divide-y divide-border">
      {lines.map((line, i) => (
        <li key={i} className="flex gap-3 px-3.5 py-1.5">
          <span className="w-8 shrink-0 text-right font-mono text-sm text-text-muted">{i + 1}</span>
          <span className="min-w-0 whitespace-pre-wrap break-words font-mono text-sm text-text">
            {line}
          </span>
        </li>
      ))}
    </ol>
  );
}
