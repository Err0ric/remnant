import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api, type M365Overview, type QueryResult } from "@/lib/api";
import { openDrill } from "@/lib/drill";
import { LoadFailed } from "@/components/LoadFailed";
import { SectionTitle } from "@/components/SectionTitle";
import { ResultsTable } from "@/features/search/ResultsTable";

interface EventListProps {
  title: string;
  /** The Search query behind the list, for Open in Logs. */
  sql: string;
  /** Which list the server runs (its SQL is built there, never sent from here). */
  list: keyof M365Overview["lists"];
  /** Sign-ins: the outcome class and kind picked. */
  filter?: { cls: string; mode: string };
  m: M365Overview;
  /** Filters shown in the header, beside the count. */
  controls?: ReactNode;
}

/** One tab's events over the page window, in the Search table (ADR-0038 section 5). */
export function EventList({ title, sql, list, filter, m, controls }: EventListProps) {
  const q = useQuery<QueryResult>({
    queryKey: ["m365-list", list, filter?.cls, filter?.mode, m.start, m.end],
    queryFn: () => api.m365List(list, m.start, m.end, filter),
  });
  return (
    <section aria-label={title} className="rounded-card border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-3 py-2">
        <SectionTitle>{title}</SectionTitle>
        {q.data ? (
          <span className="text-sm text-text-muted">
            {q.data.row_count.toLocaleString()}
            {q.data.truncated ? "+" : ""} rows
          </span>
        ) : null}
        {controls}
        <button
          type="button"
          onClick={() =>
            openDrill({ sql, from: m.start, to: m.end, origin: `Microsoft 365 > ${title}` })
          }
          className="ml-auto text-sm text-accent-text hover:underline"
        >
          Open in Logs
        </button>
      </div>
      {q.isLoading ? (
        <div aria-busy="true" className="h-40 animate-pulse bg-surface" />
      ) : q.isError ? (
        <LoadFailed
          what={title}
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
        />
      ) : q.data && q.data.row_count === 0 ? (
        <p className="p-3 text-sm text-text-secondary">Nothing in this window.</p>
      ) : q.data ? (
        <ResultsTable result={q.data} view="parsed" compact geo={q.data.geo} />
      ) : null}
    </section>
  );
}
