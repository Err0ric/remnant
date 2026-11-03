import { ApiError, type AskResponse, type QueryResult } from "@/lib/api";
import { isAborted, isModelBusy } from "@/components/ai/ModelWait";
import { cn } from "@/lib/cn";
import { AskResults } from "./AskResults";

export type Phase = "finding" | "running" | "ready" | "done" | "failed" | "cancelled" | "guidance";

export interface Turn {
  id: number;
  question: string;
  phase: Phase;
  answer?: AskResponse;
  result?: QueryResult;
  error?: unknown;
  askMs?: number;
  runMs?: number;
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
 * finding the query are one server call, then the query runs. Writing the answer joins in
 * slice 1c; a step is never shown that does not happen. */
function Progress({ phase }: { phase: Phase }) {
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
  /** Opens this turn's SQL in the SQL editor. */
  onEdit?: (sql: string) => void;
}

/** One question and what came of it, as a block, never a chat bubble (DESIGN.md 6.1): the
 * question as a heading, what the model said about its query, the rows, and a collapsed
 * "How I got this" with the SQL, where it came from, the sources read, and the time. */
export function AskTurnBlock({ turn, onRun, onRetry, onCheckData, onEdit }: AskTurnBlockProps) {
  const a = turn.answer;
  const route = a?.route ?? null;
  const working = turn.phase === "finding" || turn.phase === "running";
  return (
    <section
      aria-label={`Question: ${turn.question}`}
      className="flex flex-col gap-2.5 border-t border-border pt-3 first:border-t-0 first:pt-0"
    >
      <h3 className="text-base font-semibold [overflow-wrap:anywhere]">{turn.question}</h3>
      {working ? <Progress phase={turn.phase} /> : null}
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
      {a?.explanation ? (
        <div className="flex flex-col gap-1 text-sm">
          <p className="text-text [overflow-wrap:anywhere]">{a.explanation}</p>
          {a.assumptions.length ? (
            <ul className="ml-5 list-disc text-text-secondary">
              {a.assumptions.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          ) : null}
          <p className="text-text-muted">
            About the query, written by {a.provider.name}. The rows below come from your logs.
          </p>
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
      {turn.result ? <AskResults result={turn.result} /> : null}
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
              {onEdit ? (
                <button
                  type="button"
                  onClick={() => onEdit(a.sql)}
                  className="mt-1 text-accent-text hover:underline"
                >
                  Edit as SQL
                </button>
              ) : null}
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
