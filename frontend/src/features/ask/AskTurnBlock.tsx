import {
  ApiError,
  type AskResponse,
  type AskRunResult,
  type AskSummary,
  type Cell,
} from "@/lib/api";
import { isAborted, isModelBusy } from "@/components/ai/ModelWait";
import { cn } from "@/lib/cn";
import { AskResults } from "./AskResults";

export type Phase =
  "finding" | "running" | "writing" | "ready" | "done" | "failed" | "cancelled" | "guidance";

export interface Turn {
  id: number;
  question: string;
  phase: Phase;
  answer?: AskResponse;
  result?: AskRunResult;
  error?: unknown;
  askMs?: number;
  runMs?: number;
  /** The answer step will run (summaries on, rows with event ids). */
  willSummarize?: boolean;
  summary?: AskSummary;
  /** Why there is no summary (no event ids to cite, or the step failed). */
  summaryNote?: string;
  summaryMs?: number;
  drillError?: string;
}

const CHECK: Record<AskResponse["check"], string> = {
  ok: "The query runs and returns rows",
  empty: "The query runs but matched no rows",
  failed: "The query did not pass the check",
  library: "A shipped library query, tested on sample logs",
  none: "Nothing to run",
};

function errorText(err: unknown): string {
  if (isAborted(err)) return "Cancelled.";
  if (!(err instanceof ApiError)) return "The question could not be answered";
  if (err.code === "classification_blocked")
    return `${err.message}. Choose a local provider, or filter to cloud-allowed sources.`;
  return err.message;
}

function seconds(ms: number | undefined): string {
  return ms === undefined ? "" : `${(ms / 1000).toFixed(1)} s`;
}

/** The steps Ask performs, in order (ADR-0042 row 16): understanding the question and
 * finding the query are one server call, then the query runs, then (summaries on, rows
 * with event ids) the answer is written. A step is never shown that does not happen. */
function Progress({ phase, writing }: { phase: Phase; writing: boolean }) {
  const steps: { label: string; state: "done" | "now" | "todo" }[] = [
    {
      label: "Understanding and finding the right query",
      state: phase === "finding" ? "now" : "done",
    },
    {
      label: "Running",
      state: phase === "running" ? "now" : phase === "finding" ? "todo" : "done",
    },
  ];
  if (writing || phase === "writing")
    steps.push({ label: "Writing the answer", state: phase === "writing" ? "now" : "todo" });
  return (
    <ol aria-label="Progress" aria-live="polite" className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
      {steps.map((s) => (
        <li
          key={s.label}
          aria-current={s.state === "now" ? "step" : undefined}
          className={cn(
            s.state === "now" && "font-semibold text-text",
            s.state === "done" && "text-text-secondary",
            s.state === "todo" && "text-text-muted",
          )}
        >
          {s.label}
          {s.state === "now" ? "…" : s.state === "done" ? ", done" : ""}
        </li>
      ))}
    </ol>
  );
}

interface AskTurnBlockProps {
  turn: Turn;
  onRun: (turn: Turn) => void;
  onRetry: (turn: Turn) => void;
  /** "Check your data instead": the same question as a data question (condition 3). */
  onCheckData: (turn: Turn) => void;
  /** "Open in Logs" (D206): this turn's SQL in the Logs SQL mode. */
  onEdit?: (sql: string) => void;
  /** "Show events" for one row of an aggregate library answer (D173). */
  onShowEvents?: (turn: Turn, values: Record<string, Cell>) => void;
  /** Admins: opens the provider's edit form, where Thinking is set (D192). */
  onFixThinking?: () => void;
}

/** One question and what came of it, as a block, never a chat bubble (DESIGN.md 6.1): the
 * question as a heading, what the model said about its query, the rows, and a collapsed
 * "How I got this" with the SQL, where it came from, the sources read, and the time. */
export function AskTurnBlock({
  turn,
  onRun,
  onRetry,
  onCheckData,
  onEdit,
  onShowEvents,
  onFixThinking,
}: AskTurnBlockProps) {
  const a = turn.answer;
  const route = a?.route ?? null;
  const working = turn.phase === "finding" || turn.phase === "running" || turn.phase === "writing";
  return (
    <section
      aria-label={`Question: ${turn.question}`}
      className="flex flex-col gap-2.5 border-t border-border pt-3 first:border-t-0 first:pt-0"
    >
      <h3 className="text-base font-semibold [overflow-wrap:anywhere]">{turn.question}</h3>
      {working ? <Progress phase={turn.phase} writing={Boolean(turn.willSummarize)} /> : null}
      {turn.phase === "guidance" ? (
        <div role="status" className="flex flex-col gap-1 text-sm">
          <p>
            Treated as general guidance.{" "}
            <button
              type="button"
              onClick={() => onCheckData(turn)}
              className="font-semibold text-accent-text hover:underline"
            >
              Check your data instead?
            </button>
          </p>
          <p className="text-text-muted">
            General guidance answers are not available yet; Ask can look in your logs.
          </p>
        </div>
      ) : route && route.kind === "data" && turn.phase !== "finding" ? (
        <p className="text-sm text-text-secondary">
          {route.library ? (
            <>
              From the query library: <span className="text-text">{route.library.name}</span>
            </>
          ) : (
            "Treated as a question about your data"
          )}
          {route.time ? `, ${route.time}` : ""}
          {route.filters.length
            ? `, ${route.filters.length === 1 ? "1 filter" : `${route.filters.length} filters`}`
            : ""}
          .
        </p>
      ) : null}
      {turn.phase === "failed" || turn.phase === "cancelled" ? (
        <div
          role="alert"
          className={cn(
            "flex flex-wrap items-center gap-3 rounded border px-3 py-2 text-sm",
            isModelBusy(turn.error) ? "border-warn" : "border-danger text-sev-critical-text",
          )}
        >
          <span>{errorText(turn.error)}</span>
          {onFixThinking &&
          turn.error instanceof ApiError &&
          turn.error.code === "provider_output_limit" ? (
            <button
              type="button"
              onClick={onFixThinking}
              className="h-7 rounded border border-border-strong px-3 text-text hover:bg-surface-head"
            >
              Set Thinking to Off
            </button>
          ) : null}
          {!isAborted(turn.error) ? (
            <button
              type="button"
              onClick={() => onRetry(turn)}
              className="h-7 rounded border border-border-strong px-3 text-text hover:bg-surface-head"
            >
              Try again
            </button>
          ) : null}
        </div>
      ) : null}
      {turn.phase === "ready" && a ? (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <button
            type="button"
            onClick={() => onRun(turn)}
            className="h-8 rounded border border-accent px-4 font-semibold text-accent-text hover:bg-accent-subtle"
          >
            Run query
          </button>
          <span className="text-text-muted">
            {a.check === "failed"
              ? "The query did not pass the check; read it under How I got this first."
              : "This install runs Ask queries only when you choose Run query."}
          </span>
        </div>
      ) : null}
      {turn.result ? <Answer turn={turn} /> : null}
      {turn.result ? (
        <AskResults
          result={turn.result}
          drillKeys={turn.result.drill_keys}
          onShowEvents={onShowEvents ? (values) => onShowEvents(turn, values) : undefined}
        />
      ) : null}
      {turn.drillError ? (
        <p role="alert" className="text-sm text-sev-critical-text">
          {turn.drillError}
        </p>
      ) : null}
      {a && turn.phase !== "guidance" && onEdit ? (
        <div className="text-sm">
          <button
            type="button"
            onClick={() => onEdit(a.sql)}
            className="text-accent-text hover:underline"
          >
            Open in Logs
          </button>
          <span className="text-text-muted">
            {" "}
            · the SQL in the Logs SQL mode, to change or save
          </span>
        </div>
      ) : null}
      {a && turn.phase !== "guidance" ? (
        <details className="rounded border border-border bg-surface text-sm">
          <summary className="cursor-pointer px-3 py-1.5 text-text-secondary">
            How I got this
          </summary>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 px-3 pb-3 pt-1">
            <dt className="text-text-secondary">Query</dt>
            <dd>
              {route?.library ? (
                <>
                  Library: {route.library.name}{" "}
                  <span className="font-mono text-text-muted">
                    {route.library.ref}@{route.library.version}
                  </span>
                </>
              ) : (
                "Generated query (not from the library)"
              )}
              {route?.reason ? <span className="block text-text-muted">{route.reason}</span> : null}
            </dd>
            {a.explanation ? (
              <>
                <dt className="text-text-secondary">About the query</dt>
                <dd className="[overflow-wrap:anywhere]">
                  {a.explanation}
                  {a.assumptions.map((x, i) => (
                    <span key={i} className="block text-text-secondary">
                      Assumed: {x}
                    </span>
                  ))}
                  <span className="block text-text-muted">
                    Written by {a.provider.name}, about the query, not the rows.
                  </span>
                </dd>
              </>
            ) : null}
            {route?.filters.length ? (
              <>
                <dt className="text-text-secondary">Filters</dt>
                <dd className="font-mono">
                  {route.filters.map((f) => (
                    <span key={f} className="block">
                      {f}
                    </span>
                  ))}
                </dd>
              </>
            ) : null}
            {route?.time ? (
              <>
                <dt className="text-text-secondary">Time</dt>
                <dd>{route.time}</dd>
              </>
            ) : null}
            <dt className="text-text-secondary">Route</dt>
            <dd>
              {route?.by === "follow_up"
                ? "Follow-up: refined from the last query"
                : route?.by === "forced"
                  ? "A data question (you chose Check your data)"
                  : "A data question"}
            </dd>
            <dt className="text-text-secondary">SQL</dt>
            <dd>
              <pre
                aria-label="Generated SQL"
                className="m-0 overflow-x-auto whitespace-pre-wrap rounded bg-inset px-2.5 py-2 font-mono"
              >
                {a.sql}
              </pre>
            </dd>
            <dt className="text-text-secondary">Check</dt>
            <dd>
              {CHECK[a.check]}
              {a.attempts > 1 ? ` (${a.attempts} attempts)` : ""}
              {a.check === "failed" && a.check_detail ? (
                <span className="block font-mono text-sev-critical-text">{a.check_detail}</span>
              ) : null}
            </dd>
            <dt className="text-text-secondary">Sources read</dt>
            <dd className="font-mono">
              {turn.result ? turn.result.sources.join(", ") || "None" : "Not run yet"}
            </dd>
            <dt className="text-text-secondary">Took</dt>
            <dd className="tabular-nums">
              Finding the query {seconds(turn.askMs)}
              {turn.runMs !== undefined ? `, running ${seconds(turn.runMs)}` : ""}
              {turn.summaryMs !== undefined
                ? `, writing the answer ${seconds(turn.summaryMs)}`
                : ""}
            </dd>
            <dt className="text-text-secondary">Model</dt>
            <dd>
              {a.provider.name} · <span className="font-mono">{a.provider.model}</span> ·{" "}
              {a.provider.locality === "local" ? "Local" : "Cloud"}
            </dd>
          </dl>
        </details>
      ) : null}
    </section>
  );
}

/** The tail of an event id: UUIDv7 ids share their first characters across a batch. */
function shortId(id: string): string {
  return id.replace(/-/g, "").slice(-8);
}

/** The answer (ADR-0042 row 8, slice 1c): a headline written by code from the rows, then
 * only statements that cite rows that were sent (C1). When the model's statements could
 * not cite, there is no summary and the note says why; the rows stand alone. */
function Answer({ turn }: { turn: Turn }) {
  const head = turn.summary?.headline ?? turn.result?.headline;
  const claims = turn.summary?.claims ?? [];
  const note = turn.summary?.note ?? turn.summaryNote;
  return (
    <div className="flex flex-col gap-1.5 text-sm">
      {head ? <p className="font-semibold [overflow-wrap:anywhere]">{head}</p> : null}
      {claims.length ? (
        <ul aria-label="Summary" className="ml-5 flex list-disc flex-col gap-1">
          {claims.map((c, i) => (
            <li key={i} className="[overflow-wrap:anywhere]">
              <span>{c.text}</span>{" "}
              <span className="inline-flex flex-wrap gap-1 align-middle">
                {c.event_ids.map((id) => (
                  <span
                    key={id}
                    title={id}
                    className="rounded-badge bg-sev-info-bg px-1.5 py-px font-mono text-xs text-text-secondary"
                  >
                    {shortId(id)}
                  </span>
                ))}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {claims.length && turn.answer ? (
        <p className="text-text-muted">
          Summary by {turn.answer.provider.name}; every statement cites rows below.
        </p>
      ) : null}
      {note ? <p className="text-text-muted">{note}</p> : null}
    </div>
  );
}
