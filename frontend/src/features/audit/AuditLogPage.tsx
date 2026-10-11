import { useInfiniteQuery, useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Command, PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api, type AuditEvent, type AuditLlmCall } from "@/lib/api";
import { ActivityTable } from "./ActivityTable";
import { AiCallsTable } from "./AiCallsTable";
import {
  AuditFilterBar,
  toApiFilters,
  type AuditFilterState,
  type AuditLog,
} from "./AuditFilterBar";

const PAGE = 100;
const EMPTY: AuditFilterState = { text: "", outcome: "", range: "24h", user: null };

function save(text: string, name: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/** Audit log (Slice 5): admins and auditors read and export the append-only trail. */
export function AuditLogPage() {
  const [log, setLog] = useState<AuditLog>("activity");
  const [filters, setFilters] = useState<AuditFilterState>(EMPTY);
  const apiFilters = toApiFilters(filters);
  // The time window is fixed when the filters change, not on every render.
  const key = [log, filters.text, filters.outcome, filters.range, filters.user?.id];

  const activity = useInfiniteQuery({
    queryKey: ["audit", ...key],
    enabled: log === "activity",
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) => api.auditEvents(apiFilters, pageParam),
    getNextPageParam: (last: AuditEvent[]) =>
      last.length === PAGE ? last[last.length - 1]?.audit_id : undefined,
  });
  const calls = useInfiniteQuery({
    queryKey: ["audit", ...key],
    enabled: log === "ai",
    initialPageParam: undefined as { ts: string; id: string } | undefined,
    queryFn: ({ pageParam }) => api.auditCalls(apiFilters, pageParam),
    getNextPageParam: (last: AuditLlmCall[]) => {
      const tail = last[last.length - 1];
      return last.length === PAGE && tail ? { ts: tail.ts, id: tail.call_id } : undefined;
    },
  });
  const exporter = useMutation({
    mutationFn: async () => {
      const csv = await api.auditExport(log === "activity" ? "events" : "llm-calls", apiFilters);
      save(csv, log === "activity" ? "audit-activity.csv" : "audit-ai-calls.csv");
    },
  });

  const query = log === "activity" ? activity : calls;
  const eventRows = activity.data?.pages.flat() ?? [];
  const callRows = calls.data?.pages.flat() ?? [];
  const count = log === "activity" ? eventRows.length : callRows.length;
  const onUser = (user: { id: string; name: string }) => setFilters({ ...filters, user });

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        crumbs={["Home", "Configuration", "Audit log"]}
        title="Audit log"
        meta="Append-only · reading and exporting are recorded here too"
        commands={
          <Command
            label={exporter.isPending ? "Exporting…" : "Export CSV"}
            primary
            onClick={() => exporter.mutate()}
            disabled={exporter.isPending || count === 0}
          />
        }
      />
      <div className="flex flex-col gap-2.5 px-5 py-3">
        <div role="tablist" aria-label="Which log" className="flex gap-1 border-b border-border">
          {(
            [
              ["activity", "Activity"],
              ["ai", "AI calls"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={log === id}
              onClick={() => {
                setLog(id);
                setFilters({ ...filters, text: "", outcome: "" });
              }}
              className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${
                log === id
                  ? "border-accent font-semibold text-text"
                  : "border-transparent text-text-secondary hover:text-text"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <AuditFilterBar log={log} value={filters} onChange={setFilters} />
        {query.error || exporter.error ? (
          <p role="alert" className="text-sm text-danger">
            {(query.error ?? exporter.error) instanceof ApiError
              ? (query.error ?? exporter.error)?.message
              : "Could not load the audit log"}
          </p>
        ) : null}
      </div>
      <section
        aria-label="Audit entries"
        className="mx-5 mb-5 rounded border border-border bg-surface"
      >
        {query.isPending ? (
          <p className="px-3 py-6 text-center text-sm text-text-secondary">Loading…</p>
        ) : count === 0 ? (
          <p className="px-3 py-6 text-center text-sm text-text-secondary">
            Nothing matches these filters. Try a longer time range.
          </p>
        ) : log === "activity" ? (
          <ActivityTable rows={eventRows} onUser={onUser} />
        ) : (
          <AiCallsTable rows={callRows} onUser={onUser} />
        )}
        {query.hasNextPage ? (
          <div className="border-t border-border px-3 py-2 text-center">
            <button
              type="button"
              onClick={() => void query.fetchNextPage()}
              disabled={query.isFetchingNextPage}
              className="rounded px-3 py-1 text-sm text-accent-text hover:bg-surface-head"
            >
              {query.isFetchingNextPage ? "Loading…" : "Load older entries"}
            </button>
          </div>
        ) : null}
      </section>
    </div>
  );
}
