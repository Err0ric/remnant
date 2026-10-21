import type { SourceStatus } from "@/lib/api";

const LABELS: Record<SourceStatus["state"], { label: string; dot: string }> = {
  reading: { label: "Reading", dot: "bg-ok" },
  waiting: { label: "Waiting for first pass", dot: "bg-text-muted" },
  error: { label: "Error", dot: "bg-danger" },
  disabled: { label: "Disabled", dot: "bg-border-strong" },
};

interface SourceStateProps {
  status: SourceStatus;
}

/** Status dot plus label; never color alone (DESIGN.md). */
export function SourceState({ status }: SourceStateProps) {
  const { label, dot } = LABELS[status.state];
  return (
    <span className="flex flex-col gap-0.5">
      <span className="flex items-center gap-1.5">
        <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
        <span className={status.state === "error" ? "text-danger" : "text-text"}>{label}</span>
      </span>
      {status.error ? (
        <span className="max-w-[320px] text-sm text-text-secondary">{status.error}</span>
      ) : null}
      {status.warnings?.length ? (
        <ul className="max-w-[320px] text-sm text-warn">
          {status.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
      {status.state === "error" && status.retry_at ? (
        <span className="text-sm text-text-muted">
          Next try {new Date(status.retry_at).toLocaleTimeString()}
        </span>
      ) : null}
      {status.files_waiting > 0 ? (
        <span className="max-w-[320px] text-sm text-text-secondary">
          {status.files_waiting === 1
            ? "1 .evtx file looks"
            : `${status.files_waiting} .evtx files look`}{" "}
          partly copied, probably still being written; read in full once it stops changing, at most
          10 minutes
        </span>
      ) : null}
      {status.records_skipped > 0 ? (
        <span className="max-w-[320px] text-sm text-text-secondary">
          {status.records_skipped.toLocaleString()}{" "}
          {status.records_skipped === 1 ? "record" : "records"} could not be read (latest read); see
          the server log
        </span>
      ) : null}
    </span>
  );
}
