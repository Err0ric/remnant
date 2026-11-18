import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { EventIdChip } from "@/components/EventIdChip";
import { Skeleton } from "@/components/Skeleton";
import { When } from "@/components/When";
import { LocalityBadge } from "@/features/providers/LocalityBadge";
import {
  api,
  ApiError,
  type AskJobStep,
  type AskResponse,
  type AskRunResult,
  type AskSummary,
  type Cell,
} from "@/lib/api";
import { isModelBusy } from "@/components/ai/ModelWait";
import { cn } from "@/lib/cn";
import { fitsInLogs, TOO_LONG_FOR_LOGS } from "@/lib/sqlLimit";
import { AskDirectAnswer } from "./AskDirectAnswer";
import { AskResults } from "./AskResults";
import { EmptyAddress, addressIn } from "@/features/investigate/EmptyAddress";

export type Phase =
  "finding" | "running" | "writing" | "ready" | "done" | "failed" | "guidance" | "lookup";

export interface Turn {
  id: number;
  question: string;
  phase: Phase;
  /** When it was asked, and where the chosen model is, for the heading line (D256). */
  askedAt?: string;
  locality?: "local" | "cloud";
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
  /** The job's steps so far (D269), and when this page first saw each one running. */
  steps?: AskJobStep[];
  seen?: Partial<Record<AskJobStep["name"], number>>;
}

const CHECK: Record<AskResponse["check"], string> = {
  ok: "The query runs and returns rows",
  empty: "The query runs but matched no rows",
  failed: "The query did not pass the check",
  library: "A shipped library query, tested on sample logs",
  none: "Nothing to run",
};

function errorText(err: unknown): string {
  if (!(err instanceof ApiError)) return "The question could not be answered";
  if (err.code === "classification_blocked")
    return `${err.message}. Choose a local provider, or filter to cloud-allowed sources.`;
  return err.message;
}

function seconds(ms: number | undefined): string {
  if (ms === undefined) return "";
  return ms < 100 ? "under 0.1 s" : `${(ms / 1000).toFixed(1)} s`;
}

const STEP: Record<AskJobStep["name"], string> = {
  sql: "Writing query",
  run: "Running query",
  summary: "Summarizing",
};

/** The steps Ask performs, in order (ADR-0042 row 16, D269), as the job reports them: each
 * finished step with its time, the current one with a live elapsed time. A step is never
 * shown before it starts, so none is shown that does not happen. While a model step has
 * waited a couple of seconds, it says when the model is busy with other requests
 * (ADR-0028 row 10). */
function Progress({ turn, providerId }: { turn: Turn; providerId: string }) {
  const [now, setNow] = useState(Date.now());
  const steps = turn.steps?.length
    ? turn.steps
    : [{ name: "sql" as const, state: "running" as const, ms: null }];
  const current = steps.find((s) => s.state === "running");
  const ticking = current !== undefined;
  useEffect(() => {
    if (!ticking) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [ticking]);
  const since = current ? (turn.seen?.[current.name] ?? now) : now;
  const elapsed = Math.max(0, Math.round((now - since) / 1000));
  const model = current !== undefined && current.name !== "run" && providerId !== "";
  const queue = useQuery({
    queryKey: ["provider-queue", providerId],
    queryFn: () => api.providerQueue(providerId),
    enabled: model && elapsed >= 2,
    refetchInterval: 2000,
  });
  const q = queue.data;
  const waiting =
    model && q !== undefined && q.slots !== null && (q.waiting > 0 || q.running > q.slots);
  return (
    <div className="text-sm">
      {/* Each step is announced when it starts; the seconds are not. */}
      <p aria-live="polite" className="sr-only">
        {current ? STEP[current.name] : ""}
      </p>
      <ol aria-label="Progress" className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        {steps.map((s, i) => (
          <li
            key={s.name}
            aria-current={s.state === "running" ? "step" : undefined}
            className={cn(
              "flex items-baseline gap-2 tabular-nums",
              s.state === "running" ? "font-semibold text-text" : "text-text-secondary",
            )}
          >
            {i > 0 ? (
              <span aria-hidden="true" className="font-normal text-text-muted">
                ›
              </span>
            ) : null}
            {s.state === "running" ? (
              <span>
                {STEP[s.name]}… {elapsed} s
                {waiting ? (
                  <span className="font-normal text-text-secondary">
                    {" "}
                    · model busy, waiting for a free slot
                  </span>
                ) : null}
              </span>
            ) : (
              <span>
                {STEP[s.name]}
                {s.state === "done" ? " " : " stopped at "}
                {seconds(s.ms ?? undefined)}
              </span>
            )}
          </li>
        ))}
      </ol>
    </div>
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
  /** The thread's range start, for the no-events lines under an empty answer (B5). */
  start?: string;
  /** The chosen model, to say when it is busy with other requests. */
  providerId?: string;
  /** Why the controls that start a question do nothing now (one question runs at a time). */
  busy?: string;
}

/** One question and what came of it, as a block, never a chat bubble (DESIGN.md 6.1): the
 * question as a heading with its time and the Local or Cloud badge on the same line, what the model said about its query, the rows, and a collapsed
 * "How I got this" with the SQL, where it came from, the sources read, and the time. */
export function AskTurnBlock({
  turn,
  onRun,
  onRetry,
  onCheckData,
  onEdit,
  onShowEvents,
  onFixThinking,
  start,
  providerId = "",
  busy,
}: AskTurnBlockProps) {
  // Run query, Try again, and Check your data each start a question: while one runs they
  // stay focusable, aria-disabled, and say why (D269).
  const why = `busy-${turn.id}`;
  const starts = (go: () => void) => ({
    "aria-disabled": busy ? true : undefined,
    "aria-describedby": busy ? why : undefined,
    onClick: () => (busy ? undefined : go()),
  });
  const a = turn.answer;
  const route = a?.route ?? null;
  const locality = a?.provider.locality ?? turn.locality;
  const working = turn.phase === "finding" || turn.phase === "running" || turn.phase === "writing";
  return (
    <section
      aria-label={`Question: ${turn.question}`}
      className="flex flex-col gap-2.5 border-t border-border pt-3 first:border-t-0 first:pt-0"
    >
      <div data-turn-head="" className="flex items-baseline gap-3">
        <h3 className="min-w-0 flex-1 text-base font-semibold [overflow-wrap:anywhere]">
          {turn.question}
        </h3>
        {turn.askedAt ? (
          <When iso={turn.askedAt} className="shrink-0 text-sm text-text-muted" />
        ) : null}
        {/* No model badge on a direct lookup: no model was used (D276). */}
        {locality && turn.phase !== "lookup" ? (
          <span className="shrink-0 self-center">
            <LocalityBadge locality={locality} />
          </span>
        ) : null}
      </div>
      {busy ? (
        <span id={why} className="sr-only">
          {busy}
        </span>
      ) : null}
      {(working || turn.steps?.length) && turn.phase !== "lookup" ? (
        <Progress turn={turn} providerId={providerId} />
      ) : null}
      {turn.phase === "lookup" && a?.lookup ? <AskDirectAnswer found={a.lookup} /> : null}
      {turn.phase === "guidance" ? (
        <div role="status" className="flex flex-col gap-1 text-sm">
          <p>
            Treated as general guidance.{" "}
            <button
              type="button"
              {...starts(() => onCheckData(turn))}
              className={cn(
                "font-semibold",
                busy ? "cursor-default text-text-muted" : "text-accent-text hover:underline",
              )}
            >
              Check your data instead?
            </button>
          </p>
          <p className="text-text-muted">
            General guidance answers are not available yet; Ask can look in your logs.
          </p>
        </div>
      ) : route && route.kind === "data" && turn.phase !== "finding" && turn.phase !== "lookup" ? (
        <p className="text-sm text-text-secondary">
          {route.library ? (
            <>
              From the query library: <span className="text-text">{route.library.name}</span>
            </>
          ) : (
            "Treated as a question about your data"
          )}
          {/* The question's own time wins over the picker: say so (owner, 2026-11-08). */}
          {route.time ? `, ${route.time} (named in the question, not the time range above)` : ""}
          {route.filters.length
            ? `, ${route.filters.length === 1 ? "1 filter" : `${route.filters.length} filters`}`
            : ""}
          .
        </p>
      ) : turn.phase === "finding" ? (
        // The routing line's row, held until the query is written, so nothing moves then.
        <p aria-hidden="true" className="text-sm">
          {"\u00a0"}
        </p>
      ) : null}
      {turn.phase === "failed" ? (
        <div
          role="alert"
          className={cn(
            "flex flex-wrap items-center gap-3 rounded border px-3 py-2 text-sm",
            isModelBusy(turn.error) ? "border-warn" : "border-danger text-danger",
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
          <button
            type="button"
            {...starts(() => onRetry(turn))}
            className={cn(
              "h-7 rounded border border-border-strong px-3",
              busy ? "cursor-default text-text-muted" : "text-text hover:bg-surface-head",
            )}
          >
            Try again
          </button>
        </div>
      ) : null}
      {turn.phase === "ready" && a ? (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <button
            type="button"
            {...starts(() => onRun(turn))}
            className={cn(
              "h-8 rounded border px-4 font-semibold",
              busy
                ? "cursor-default border-border-strong text-text-muted"
                : "border-accent text-accent-text hover:bg-accent-subtle",
            )}
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
      {turn.result && !(turn.result.counted && turn.result.rows.length === 0) ? (
        <AskResults
          result={turn.result}
          drillKeys={turn.result.drill_keys}
          onShowEvents={onShowEvents ? (values) => onShowEvents(turn, values) : undefined}
        />
      ) : null}
      {turn.summary?.timed_out && turn.summary.note ? (
        // Under the table it names (D270): the rows stand without a summary.
        <p role="status" className="text-sm text-text-muted">
          {turn.summary.note}
        </p>
      ) : null}
      {turn.result && turn.result.rows.length === 0 && addressIn(turn.question) ? (
        // Written by code from the server's facts, never by the model (ADR-0045 B5).
        <EmptyAddress
          value={addressIn(turn.question) ?? ""}
          start={start}
          rangeWords="this time range"
        />
      ) : null}
      {turn.drillError ? (
        <p role="alert" className="text-sm text-danger">
          {turn.drillError}
        </p>
      ) : null}
      {a && turn.phase !== "guidance" && turn.phase !== "lookup" && onEdit ? (
        !fitsInLogs(a.sql) ? (
          // Built by the server from the AI catalog, longer than Logs takes (fix 20).
          <div className="text-sm">
            <button
              type="button"
              aria-disabled="true"
              aria-describedby={`too-long-${turn.id}`}
              className="cursor-default text-text-muted"
            >
              Open in Logs
            </button>
            <span id={`too-long-${turn.id}`} className="text-text-muted">
              {" "}
              · {TOO_LONG_FOR_LOGS}
            </span>
          </div>
        ) : (
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
        )
      ) : null}
      {a && turn.phase !== "guidance" && turn.phase !== "lookup" ? (
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
                  : route?.by === "library"
                    ? "A data question, matched to the library without the model"
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
                <span className="block font-mono text-danger">{a.check_detail}</span>
              ) : null}
            </dd>
            <dt className="text-text-secondary">Sources read</dt>
            <dd className="font-mono">
              {turn.result ? turn.result.sources.join(", ") || "None" : "Not run yet"}
            </dd>
            <dt className="text-text-secondary">Took</dt>
            <dd className="tabular-nums">
              Writing the query {seconds(turn.askMs)}
              {turn.runMs !== undefined ? `, running it ${seconds(turn.runMs)}` : ""}
              {turn.summaryMs !== undefined ? `, summarizing ${seconds(turn.summaryMs)}` : ""}
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
  const counted = turn.result?.counted;
  // No rows and a counted line: that line is the whole answer (fix list 2026-11-16).
  if (counted && turn.result?.rows.length === 0)
    return <p className="text-sm [overflow-wrap:anywhere]">{counted}</p>;
  const head = turn.summary?.headline ?? turn.result?.headline;
  const claims = turn.summary?.claims ?? [];
  // The counted line says why there is no summary; the note would repeat it.
  // A timed-out summary's note is drawn under the table it points to.
  const note = counted || turn.summary?.timed_out ? null : (turn.summary?.note ?? turn.summaryNote);
  // While the summary is written, and after, the summary area holds the height of two
  // statements and the model line, so the table does not move when the summary arrives.
  // The bars show only while the summary is being written (the job still runs); a summary
  // that failed or stopped leaves no placeholder behind.
  const writing = !turn.summary && (turn.phase === "writing" || turn.phase === "running");
  const hold =
    Boolean(turn.willSummarize) && !turn.summary?.timed_out && (Boolean(turn.summary) || writing);
  const summary = (
    <>
      {claims.length ? (
        <ul aria-label="Summary" className="ml-5 flex list-disc flex-col gap-1">
          {claims.map((c, i) => (
            <li key={i} className="[overflow-wrap:anywhere]">
              <span>{c.text}</span>{" "}
              <span className="inline-flex flex-wrap gap-1 align-middle">
                {c.event_ids.map((id) => (
                  <EventIdChip key={id} id={id} label={shortId(id)} />
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
    </>
  );
  return (
    <div className="flex flex-col gap-1.5 text-sm">
      {head ? <p className="font-semibold [overflow-wrap:anywhere]">{head}</p> : null}
      {hold ? (
        <div data-summary-area="" className="grid">
          <div aria-hidden="true" className="invisible flex flex-col gap-1.5 [grid-area:1/1]">
            <ul className="ml-5 flex list-disc flex-col gap-1">
              {[0, 1].map((i) => (
                <li key={i} className="[overflow-wrap:anywhere]">
                  x {/* The same markup as a statement's ids, so the line is as tall. */}
                  <span className="inline-flex flex-wrap gap-1 align-middle">
                    <EventIdChip id="" label="00000000" />
                  </span>
                </li>
              ))}
            </ul>
            <p>x</p>
          </div>
          <div className="flex flex-col gap-1.5 [grid-area:1/1]">
            {turn.summary ? (
              summary
            ) : (
              <div aria-hidden="true" className="flex flex-col gap-2 pt-1">
                <Skeleton
                  label="the summary"
                  block="h-3"
                  className="w-3/5 border-0 bg-transparent"
                />
                <Skeleton
                  label="the summary"
                  block="h-3"
                  className="w-2/5 border-0 bg-transparent"
                />
              </div>
            )}
          </div>
        </div>
      ) : (
        summary
      )}
      {counted ? (
        <p className="text-text-secondary [overflow-wrap:anywhere]">
          <span className="font-semibold">What was counted:</span> {counted}
        </p>
      ) : null}
      {note ? <p className="text-text-muted">{note}</p> : null}
    </div>
  );
}
