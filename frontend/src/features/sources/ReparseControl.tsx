import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { When } from "@/components/When";
import { ApiError, api, type ReparseJob, type ReparseStatus } from "@/lib/api";
import { AUTO_PARSER } from "@/lib/parsers";

interface ReparseControlProps {
  sourceId: string;
  templateId: string | null;
  canManage: boolean;
  /** The source list's `reparse_pending`: only then is the exact count asked for. */
  pending: boolean;
}

function count(n: number, one: string, many: string): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

function JobLine({ job }: { job: ReparseJob }) {
  if (job.state === "running") {
    return (
      <span className="text-sm text-text-secondary">
        Reparsing: {job.rows_rewritten.toLocaleString()} of{" "}
        {count(job.rows_found, "event", "events")}
      </span>
    );
  }
  if (job.state === "done") {
    return (
      <span className="text-sm text-text-secondary">
        Reparsed {count(job.rows_rewritten, "event", "events")} in{" "}
        {count(job.files_rewritten, "file", "files")}, <When iso={job.finished_at} />
      </span>
    );
  }
  const label = job.state === "failed" ? "Reparse failed" : "Reparse interrupted";
  return (
    <span className={`text-sm ${job.state === "failed" ? "text-danger" : "text-warn"}`}>
      {label} after {count(job.rows_rewritten, "event", "events")}: {job.error ?? ""}
    </span>
  );
}

/** Events stored without the source's template while it was missing can be parsed with it
 * once it loads again (ADR-0050 row 7). Admins only; the job runs on the server. */
export function ReparseControl({
  sourceId,
  templateId,
  canManage,
  pending: offered,
}: ReparseControlProps) {
  const client = useQueryClient();
  // A job this page saw running is followed to its end, even once the source list stops
  // flagging the source (the flag goes when the job is done).
  const seen = client.getQueryData<ReparseStatus>(["source-reparse", sourceId]);
  const allowed = canManage && templateId !== null && templateId !== AUTO_PARSER;
  const enabled = allowed && (offered || seen?.job?.state === "running");
  const [confirming, setConfirming] = useState(false);
  const status = useQuery({
    queryKey: ["source-reparse", sourceId],
    queryFn: () => api.reparseStatus(sourceId),
    enabled,
    staleTime: 60_000,
    refetchInterval: (q) => (q.state.data?.job?.state === "running" ? 3000 : false),
  });
  const start = useMutation({
    mutationFn: () => api.startReparse(sourceId),
    onSuccess: () => {
      setConfirming(false);
      void client.invalidateQueries({ queryKey: ["source-reparse", sourceId] });
    },
  });
  if (!allowed || !status.data) return null;
  const { pending, template_available: available, job } = status.data;
  const running = job?.state === "running";
  const offer = pending > 0 && available && !running;
  if (!job && !offer) return null;
  const label = `Reparse ${count(pending, "event", "events")}`;
  return (
    <span className="flex flex-col items-start gap-1 text-sm">
      {job ? <JobLine job={job} /> : null}
      {offer && !confirming ? (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="whitespace-nowrap text-accent-text hover:underline"
        >
          {label}
        </button>
      ) : null}
      {offer && confirming ? (
        <span className="flex max-w-[22rem] flex-col gap-1.5 whitespace-normal">
          <span className="text-text-secondary">
            Parse {count(pending, "event", "events")} stored without the parser again, with template{" "}
            <span className="font-mono">{templateId}</span>. Event IDs, raw lines, and times stay
            the same.
          </span>
          <span className="flex gap-2">
            <button
              type="button"
              onClick={() => start.mutate()}
              disabled={start.isPending}
              className="h-7 rounded bg-accent px-3 font-semibold text-white hover:brightness-110 disabled:opacity-50"
            >
              {start.isPending ? "Starting…" : label}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="h-7 rounded border border-border-strong px-3 hover:bg-surface-head"
            >
              Cancel
            </button>
          </span>
        </span>
      ) : null}
      {start.error ? (
        <span role="alert" className="text-danger">
          {start.error instanceof ApiError ? start.error.message : "Could not start the reparse"}
        </span>
      ) : null}
    </span>
  );
}
