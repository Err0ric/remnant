import { ApiError } from "@/lib/api";

interface InlineErrorProps {
  /** What did not load, as the section names it: "AI Watch". */
  what: string;
  error: unknown;
  onRetry: () => void;
  retrying: boolean;
}

/** An error in place (DESIGN.md 6.0, F63): a section that could not load says so where its
 * content would be, with Retry. It is never left
 * empty or dropped from the page. */
export function InlineError({ what, error, onRetry, retrying }: InlineErrorProps) {
  const api = error instanceof ApiError ? error : null;
  const reason =
    api?.code === "query_memory"
      ? "the query ran out of memory on this server; try a shorter time range"
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
