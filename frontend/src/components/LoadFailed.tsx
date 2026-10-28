import { ApiError } from "@/lib/api";

interface LoadFailedProps {
  /** What did not load, as the section names it: "AI Watch". */
  what: string;
  error: unknown;
  onRetry: () => void;
  retrying: boolean;
}

/** A section that could not load says so in place, with Retry (F63): it is never left
 * empty or dropped from the page. */
export function LoadFailed({ what, error, onRetry, retrying }: LoadFailedProps) {
  const api = error instanceof ApiError ? error : null;
  const reason =
    api?.code === "query_memory"
      ? "the query needed more memory than this server allows"
      : api?.code === "query_timeout"
        ? "the query took too long"
        : (api?.message ?? "the server could not be reached");
  return (
    <div role="alert" className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
      <span className="text-danger">
        {what} did not load: {reason}.
      </span>
      {api?.requestId ? <span className="text-text-muted">Request {api.requestId}</span> : null}
      <button
        type="button"
        onClick={onRetry}
        disabled={retrying}
        className="h-7 rounded border border-border px-2 text-text hover:bg-surface-head disabled:opacity-40"
      >
        {retrying ? "Retrying" : "Retry"}
      </button>
    </div>
  );
}
