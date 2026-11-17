import type { SourceStatus } from "@/lib/api";

/** What the reader is doing, in words: a fact beside the status, never the status itself
 * (fix list 2026-11-16 item 19: a file being followed can still have sent nothing for days). */
const READER: Record<SourceStatus["state"], string> = {
  reading: "following the files",
  waiting: "waiting for the first pass",
  error: "stopped on an error",
  disabled: "off",
};
const PUSHED: Partial<Record<SourceStatus["state"], string>> = { reading: "listening" };
const PULLED: Partial<Record<SourceStatus["state"], string>> = { reading: "fetching" };

interface SourceStateProps {
  status: SourceStatus;
  kind?: string;
}

function readerWords(state: SourceStatus["state"], kind: string | undefined): string {
  if (kind === "otlp" || kind === "syslog") return PUSHED[state] ?? READER[state];
  if (kind && kind !== "file") return PULLED[state] ?? READER[state];
  return READER[state];
}

/** What the reader says under the status: "Reader: following the files", then
 * any error, warnings, and records it could not read. */
export function SourceState({ status, kind }: SourceStateProps) {
  return (
    <span className="flex flex-col gap-0.5">
      <span className="text-sm text-text-muted">Reader: {readerWords(status.state, kind)}</span>
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
      {status.time_offset_text ? (
        <span role="note" className="max-w-[320px] text-sm text-warn">
          {status.time_offset_text}.
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
