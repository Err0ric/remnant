import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { FacetSelect } from "@/components/FilterBar";
import { api, ApiError, type AskJob, type AskRequest, type Cell } from "@/lib/api";
import { closeAsk } from "@/lib/askSlideOver";
import { fitsInLogs, TOO_LONG_FOR_LOGS } from "@/lib/sqlLimit";
import { setAskProvider, useAskProvider } from "@/lib/askProvider";
import { navigate } from "@/lib/route";
import { seedSearch } from "@/lib/searchSeed";
import { LocalityBadge } from "@/features/providers/LocalityBadge";
import { cn } from "@/lib/cn";
import { AskExamples } from "./AskExamples";
import { AskTurnBlock, type Turn } from "./AskTurnBlock";
import { fromJob, halted, pollEvery, stopped } from "./askJob";

const MAX_TURNS = 3;
/** Why Ask waits while a question runs: the server takes one per person (D269). */
const STILL_RUNNING = "Your previous question is still running";
/** The prompt's height in lines: one per line typed, from two to six. */
export function promptRows(text: string): number {
  return Math.min(6, Math.max(2, text.split("\n").length));
}
/** Text that reads as a KQL or SPL query rather than a sentence: a pipe into a verb, or a
 * leading `index=` or `search`. */
const QUERY_LIKE =
  /\|\s*(where|stats|summarize|project|extend|count|table|sort|top|eval|rex|search)\b|^\s*(index|sourcetype)\s*=|^\s*search\s/i;
/** The asker's time zone, so "today" means their day. */
const TZ = (() => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return undefined;
  }
})();

interface AskThreadProps {
  start: string | undefined;
  /** The end of a Custom range; left out for a window that ends now. */
  end?: string;
  sources: string[];
  isAdmin: boolean;
  /** A question to start with (the slide-over opened from the command palette). */
  initialQuestion?: string;
  /** Opens SQL in the Logs SQL mode (Open in Logs, a library suggestion); `question` is the
   * thread's first question when the SQL is an answer. */
  onEdit?: (sql: string, question?: string) => void;
  /** The latest SQL and the first question, for Save; null after New question. */
  onAnswer?: (answer: { sql: string; question: string } | null) => void;
  /** Focus the question box on open (the slide-over). */
  autoFocus?: boolean;
  /** The page's Time and Sources chips, drawn before the Model chip (D256). */
  filters?: ReactNode;
  /** Set by a page whose header has New question: each new value starts over, and the
   * thread then draws no New question of its own. */
  startOver?: number;
  /** Whether the thread has turns, for the page's New question. */
  onTurns?: (has: boolean) => void;
}

/**
 * Ask (ADR-0042 slice 1a): a question becomes SQL that runs at once when it passes the
 * guard on the asker's own sources, unless the install keeps click-to-run. Search first
 * (D256): the prompt, then the chips, then the answers as blocks, newest first, directly
 * under the prompt; a follow-up refines the newest answer (3 turns). Only the drawing
 * order is newest first: the turns and the history sent are in the order asked.
 */
export function AskThread({
  start,
  end,
  sources,
  isAdmin,
  initialQuestion = "",
  onEdit,
  onAnswer,
  autoFocus,
  filters,
  startOver: startOverSignal,
  onTurns,
}: AskThreadProps) {
  const providerId = useAskProvider();
  const [question, setQuestion] = useState(initialQuestion);
  const [turns, setTurns] = useState<Turn[]>([]);
  const nextId = useRef(1);
  const turnsNow = useRef(turns);
  turnsNow.current = turns;
  const client = useQueryClient();
  const providers = useQuery({ queryKey: ["ask-providers"], queryFn: api.askProviders });
  const chosen =
    providers.data?.find((p) => p.provider_id === providerId) ?? providers.data?.[0] ?? null;
  const noProviders = providers.isSuccess && providers.data.length === 0;

  const update = (id: number, change: Partial<Turn>) =>
    setTurns((all) => all.map((t) => (t.id === id ? { ...t, ...change } : t)));

  // Ask runs as a job (D269): the submit returns at once and the page polls the job, so no
  // request stays open while the model works (a proxy's time limit never ends a question).
  const [active, setActive] = useState<{ turn: number; job: string } | null>(null);
  const job = useQuery({
    queryKey: ["ask-job", active?.job],
    queryFn: ({ signal }) => api.askJob(active?.job ?? "", signal),
    enabled: active !== null,
    staleTime: 0,
    // A dropped poll or a proxy's 5xx is tried again; an expired job (404) is not.
    retry: (n, e) => n < 3 && !(e instanceof ApiError && e.status >= 400 && e.status < 500),
    retryDelay: (n) => Math.min(2000, 500 * 2 ** n),
    refetchInterval: (q) =>
      q.state.data?.state === "running" && q.state.status !== "error"
        ? pollEvery(q.state.dataUpdateCount)
        : false,
  });
  // A job keeps being read after New question clears its turn: the server holds the
  // person's one question until it ends, and Ask comes back then (D269).
  const apply = (id: number, j: AskJob) => {
    const t = turnsNow.current.find((x) => x.id === id);
    if (t) {
      if (j.ask && !t.answer)
        onAnswer?.({ sql: j.ask.sql, question: turnsNow.current[0]?.question ?? t.question });
      update(id, fromJob(j, t, Date.now()));
    }
    if (j.state !== "running") setActive(null);
  };
  const fail = (id: number, error: unknown) => {
    const t = turnsNow.current.find((x) => x.id === id);
    if (t) update(id, stopped(t, error, Date.now()));
  };
  const activeNow = useRef(active);
  activeNow.current = active;
  // A 429 on a submit ("Your previous question is still running", D269) fails nothing: the
  // answers keep their state and buttons, and the reason shows as one muted line.
  const [held, setHeld] = useState<string | null>(null);
  const isHeld = (error: unknown) => error instanceof ApiError && error.status === 429;
  const follow = (id: number, j: AskJob) => {
    const was = activeNow.current;
    const left = was && was.turn !== id ? turnsNow.current.find((t) => t.id === was.turn) : null;
    if (left) update(left.id, halted(left, Date.now())); // no longer followed: steps end
    setHeld(null);
    client.setQueryData(["ask-job", j.job_id], j);
    setActive({ turn: id, job: j.job_id });
    apply(id, j);
  };
  const applyRef = useRef(apply);
  applyRef.current = apply;
  useEffect(() => {
    if (active && job.data?.job_id === active.job) applyRef.current(active.turn, job.data);
  }, [active, job.data]);
  const failRef = useRef(fail);
  failRef.current = fail;
  useEffect(() => {
    if (!active || !job.isError) return;
    failRef.current(active.turn, job.error);
    setActive(null); // every read of this job stops; its steps stopped with it
  }, [active, job.isError, job.error]);
  const asking = useMutation({
    mutationFn: ({ body }: { id: number; body: AskRequest; before: Turn[] }) => api.askJobs(body),
    onSuccess: (j, { id }) => follow(id, j),
    onError: (error, { id, body, before }) => {
      if (!isHeld(error)) return fail(id, error);
      setTurns(before); // the answers as they were, a replaced one included
      setQuestion(
        (q) => q || (before.some((t) => t.question === body.question) ? "" : body.question),
      );
      setHeld(error instanceof Error ? error.message : null);
    },
  });

  // "Show events" (D173): the server builds the row's events query from the library
  // query; Search runs it through the guard on the caller's view, audited like any query.
  const showEvents = useMutation({
    mutationFn: ({ turn, values }: { turn: Turn; values: Record<string, Cell> }) =>
      api.askDrill(turn.answer?.ask_id ?? "", values),
    onSuccess: (d, { turn }) => {
      seedSearch({
        sql: d.sql,
        window: d.start && d.end ? { from: d.start, to: d.end } : undefined,
        range: d.start && d.end ? undefined : "all",
        sources: d.sources ?? undefined,
        origin: `From Ask AI: ${turn.question}`,
      });
      closeAsk();
      navigate("logs");
    },
    onError: (error, { turn }) =>
      update(turn.id, {
        drillError: error instanceof Error ? error.message : "Could not open those events",
      }),
  });

  // Run query on a click-to-run answer (ADR-0042): the query, then the summary, as a job.
  const run = useMutation({
    mutationFn: ({ askId }: { id: number; askId: string }) => api.runJob(askId),
    onMutate: ({ id }) => {
      const before = turnsNow.current.find((t) => t.id === id);
      update(id, {
        phase: "running",
        steps: [
          ...(turnsNow.current.find((t) => t.id === id)?.steps ?? []).filter(
            (s) => s.name === "sql",
          ),
          { name: "run", state: "running", ms: null },
        ],
        seen: { run: Date.now() },
      });
      return { before };
    },
    onSuccess: (j, { id }) => follow(id, j),
    onError: (error, { id }, context) => {
      if (!isHeld(error) || !context?.before) return fail(id, error);
      update(id, context.before); // still ready, with its Run query
      setHeld(error instanceof Error ? error.message : null);
    },
  });

  const begin = (q: string, earlier: Turn[], route?: "data") => {
    const id = nextId.current++;
    const before = turnsNow.current;
    const history = earlier
      // A direct lookup (D276) has no query to refine: it never goes to the model.
      .filter((t) => t.answer && !t.answer.lookup?.length)
      .slice(-MAX_TURNS)
      // By the answer's id: the server reads its own SQL, so SQL it built (longer than
      // typed SQL may be) is never posted back; the copy goes too while it fits.
      .map((t) => ({
        question: t.question,
        ...(t.answer!.ask_id ? { ask_id: t.answer!.ask_id } : {}),
        ...(fitsInLogs(t.answer!.sql) ? { sql: t.answer!.sql } : {}),
      }));
    setTurns([
      ...earlier,
      {
        id,
        question: q,
        phase: "finding",
        askedAt: new Date().toISOString(),
        locality: chosen?.locality,
      },
    ]);
    // Nothing on the page is this question's answer until its query runs (D192).
    onAnswer?.(null);
    const body: AskRequest = {
      question: q,
      provider_id: chosen?.provider_id,
      start,
      end,
      sources: sources.length ? sources : undefined,
      history,
      tz: TZ,
      route,
    };
    asking.mutate({ id, body, before });
  };
  const busy = asking.isPending || run.isPending || active !== null;
  // New question cleared the running question's turn; the server still holds it.
  const hidden = active !== null && !turns.some((t) => t.id === active.turn);
  const ready = Boolean(question.trim()) && !busy;
  // With no AI provider, Ask still offers library queries that match the words (C4).
  const [suggestFor, setSuggestFor] = useState<string | null>(null);
  const suggestions = useQuery({
    queryKey: ["ask-suggest", suggestFor],
    queryFn: () => api.askSuggest(suggestFor ?? ""),
    enabled: suggestFor !== null,
  });
  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const q = question.trim();
    if (!q || busy) return;
    if (noProviders) {
      setSuggestFor(q);
      return;
    }
    setQuestion("");
    begin(q, turns);
  };
  // An example question, one click (D182): asked at once, or matched to the library
  // when no provider is set up.
  const askNow = (q: string) => {
    if (busy) return;
    if (noProviders) {
      setQuestion(q);
      setSuggestFor(q);
      return;
    }
    begin(q, turns);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit();
  };
  const startOver = () => {
    setTurns([]); // a job still running is still read, so Ask stays off until it ends
    onAnswer?.(null);
  };
  const startOverRef = useRef(startOver);
  startOverRef.current = startOver;
  useEffect(() => {
    if (startOverSignal) startOverRef.current();
  }, [startOverSignal]);
  const hasTurns = turns.length > 0;
  useEffect(() => onTurns?.(hasTurns), [hasTurns, onTurns]);
  const retry = (t: Turn) =>
    !busy &&
    begin(
      t.question,
      turns.filter((x) => x.id !== t.id),
    );
  // Check your data instead (ADR-0042 condition 3): the same question as a data question.
  const checkData = (t: Turn) =>
    !busy &&
    begin(
      t.question,
      turns.filter((x) => x.id !== t.id),
      "data",
    );
  const runTurn = (t: Turn) =>
    !busy && t.answer?.ask_id && run.mutate({ id: t.id, askId: t.answer.ask_id });

  return (
    <div className="flex flex-col gap-4">
      {/* The content column's width up to 1200px (DESIGN 6.1): the prompt, the chips, and
          the suggestions share it; the answers below use the full width. */}
      <div className="flex max-w-[1200px] flex-col gap-2">
        {/* Only the prompt and Ask are in the form: Enter in a chip never asks (D256). */}
        <form aria-label="Ask a question" onSubmit={submit} className="flex flex-col gap-2">
          <label htmlFor="ask-question" className="sr-only">
            Question
          </label>
          <div className="flex items-end gap-2 rounded border border-border-control bg-inset py-1.5 pl-3 pr-1.5 has-[textarea:focus]:ring-2 has-[textarea:focus]:ring-focus-ring">
            <textarea
              id="ask-question"
              // Two to six lines by the line breaks typed, where `field-sizing` is not supported.
              rows={promptRows(question)}
              maxLength={2000}
              // The slide-over opens with the cursor in the box (it is the whole panel).
              autoFocus={autoFocus}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={turns.length ? "Refine the answer below" : "Ask about your logs"}
              title="Ask in plain words, or paste a KQL or SPL query. Ctrl+Enter asks."
              // Two lines, growing with the text to six.
              className="max-h-[calc(6lh+8px)] min-h-[calc(2lh+8px)] min-w-0 flex-1 resize-none bg-transparent py-1 text-md font-normal [field-sizing:content] focus:outline-none"
            />
            {/* The page's one filled button once there is text; while empty or busy it
                stays focusable and says why it does nothing (DESIGN 6.1). */}
            <button
              type="submit"
              aria-disabled={!ready}
              aria-describedby={ready ? undefined : "ask-not-ready"}
              className={cn(
                "h-8 shrink-0 rounded px-4 font-semibold",
                ready
                  ? "bg-accent text-on-accent hover:brightness-110"
                  : "cursor-default border border-border-strong text-text-muted",
              )}
            >
              {turns.length ? "Refine" : "Ask"}
            </button>
            <span id="ask-not-ready" className="sr-only">
              {busy ? STILL_RUNNING : "Type a question first"}
            </span>
          </div>
          {hidden ? (
            <p aria-hidden="true" className="text-sm text-text-muted">
              {STILL_RUNNING}. Ask comes back when it ends.
            </p>
          ) : held && !busy ? (
            <p role="status" className="text-sm text-text-muted">
              {held}
            </p>
          ) : null}
          {QUERY_LIKE.test(question) ? (
            <p className="text-sm text-text-muted">
              Reads as a KQL or SPL query: Ask turns it into SQL for your logs.
            </p>
          ) : null}
        </form>
        <div className="flex min-h-7 flex-wrap items-center gap-2 text-sm">
          {filters}
          <FacetSelect
            name="Model"
            value={chosen?.provider_id ?? ""}
            onChange={setAskProvider}
            disabled={!providers.data?.length}
            options={
              providers.data?.length
                ? providers.data.map((p) => ({ id: p.provider_id, label: p.name }))
                : [{ id: "", label: "None" }]
            }
            after={chosen ? <LocalityBadge locality={chosen.locality} /> : undefined}
          />
          {turns.length && startOverSignal === undefined ? (
            <button
              type="button"
              onClick={startOver}
              className="ml-auto h-7 rounded border border-border-strong px-2.5 text-text hover:bg-surface-head"
            >
              New question
            </button>
          ) : null}
        </div>
        {chosen?.locality === "cloud" ? (
          <p role="note" className="text-sm text-text-muted">
            Your question is sent to {chosen.name}.
          </p>
        ) : null}
        {noProviders ? (
          <p className="text-sm text-text-secondary">
            No AI provider is set up. Logs works without one.
            {isAdmin ? (
              <>
                {" "}
                <button
                  type="button"
                  onClick={() => navigate("providers")}
                  className="text-accent-text hover:underline"
                >
                  Add a provider
                </button>
              </>
            ) : (
              " An administrator can add one."
            )}
          </p>
        ) : null}
      </div>
      {noProviders && suggestFor !== null ? (
        <section
          aria-label="Library suggestions"
          className="flex max-w-[1200px] flex-col gap-1.5 text-sm"
        >
          <h3 className="font-semibold">Library queries that match your words</h3>
          {suggestions.data?.length ? (
            <ul className="flex flex-col gap-1.5">
              {suggestions.data.map((s) => (
                <li key={s.ref}>
                  {fitsInLogs(s.sql) ? (
                    <button
                      type="button"
                      onClick={() => onEdit?.(s.sql)}
                      className="font-semibold text-accent-text hover:underline"
                    >
                      {s.name}
                    </button>
                  ) : (
                    <button
                      type="button"
                      aria-disabled="true"
                      aria-describedby={`too-long-${s.ref}`}
                      className="cursor-default font-semibold text-text-muted"
                    >
                      {s.name}
                    </button>
                  )}
                  <span className="block text-text-secondary">{s.why}</span>
                  {fitsInLogs(s.sql) ? null : (
                    <span id={`too-long-${s.ref}`} className="block text-text-muted">
                      {TOO_LONG_FOR_LOGS}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          ) : suggestions.isSuccess ? (
            <p className="text-text-secondary">No library query matches those words.</p>
          ) : null}
          <p className="text-text-muted">Each opens in the Logs SQL mode, where Run runs it.</p>
        </section>
      ) : null}
      {turns.length === 0 && suggestFor === null ? (
        <AskExamples onPick={askNow} disabled={busy} />
      ) : null}
      {turns.length ? (
        <div aria-label="Answers" className="mt-1 flex flex-col gap-4 border-t border-border pt-4">
          {/* Newest first, directly under the prompt that refines it (D256). */}
          {[...turns].reverse().map((t) => (
            <AskTurnBlock
              key={t.id}
              turn={t}
              start={start}
              busy={busy ? STILL_RUNNING : undefined}
              providerId={chosen?.provider_id ?? ""}
              onRun={runTurn}
              onRetry={retry}
              onCheckData={checkData}
              onEdit={onEdit ? (sql) => onEdit(sql, turns[0]?.question ?? t.question) : undefined}
              onShowEvents={(turn, values) => showEvents.mutate({ turn, values })}
              onFixThinking={
                isAdmin && chosen
                  ? () => {
                      closeAsk();
                      navigate("providers", `edit=${encodeURIComponent(chosen.provider_id)}`);
                    }
                  : undefined
              }
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
