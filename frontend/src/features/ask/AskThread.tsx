import { useMutation, useQuery } from "@tanstack/react-query";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { FacetSelect } from "@/components/FilterBar";
import { isAborted, ModelWait } from "@/components/ai/ModelWait";
import { api, type AskTurn, type Cell } from "@/lib/api";
import { closeAsk } from "@/lib/askSlideOver";
import { setAskProvider, useAskProvider } from "@/lib/askProvider";
import { navigate } from "@/lib/route";
import { seedSearch } from "@/lib/searchSeed";
import { LocalityBadge } from "@/features/providers/LocalityBadge";
import { cn } from "@/lib/cn";
import { AskExamples } from "./AskExamples";
import { AskTurnBlock, type Turn } from "./AskTurnBlock";

const MAX_TURNS = 3;
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
  const startedAt = useRef<Record<number, number>>({});
  const abort = useRef<AbortController | null>(null);
  const providers = useQuery({ queryKey: ["ask-providers"], queryFn: api.askProviders });
  const chosen =
    providers.data?.find((p) => p.provider_id === providerId) ?? providers.data?.[0] ?? null;
  const noProviders = providers.isSuccess && providers.data.length === 0;

  const update = (id: number, change: Partial<Turn>) =>
    setTurns((all) => all.map((t) => (t.id === id ? { ...t, ...change } : t)));

  // The answer step (slice 1c): statements that cite the rows. Any failure here leaves
  // the headline and the rows without a summary; it never fails the turn.
  const summarize = useMutation({
    mutationFn: ({ askId }: { id: number; askId: string }) => {
      abort.current = new AbortController();
      return api.askAnswer(askId, abort.current.signal);
    },
    onSuccess: (summary, { id }) =>
      update(id, {
        phase: "done",
        summary,
        summaryMs: Date.now() - (summaryStart.current[id] ?? Date.now()),
      }),
    onError: (error, { id }) =>
      update(id, {
        phase: "done",
        summaryNote: isAborted(error)
          ? "No summary: cancelled."
          : `No summary: ${error instanceof Error ? error.message : "the model did not answer"}`,
      }),
  });
  const summaryStart = useRef<Record<number, number>>({});

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

  const run = useMutation({
    mutationFn: ({ askId }: { id: number; askId: string }) => {
      abort.current = new AbortController();
      return api.runAnswer(askId, abort.current.signal);
    },
    onMutate: ({ id }) => update(id, { phase: "running" }),
    onSuccess: (result, { id, askId }) => {
      const writing = result.summarize && result.rows.length > 0;
      update(id, {
        phase: writing ? "writing" : "done",
        result,
        runMs: result.elapsed_ms,
        summaryNote: result.summary_note ?? undefined,
        willSummarize: writing,
      });
      if (writing) {
        summaryStart.current[id] = Date.now();
        summarize.mutate({ id, askId });
      }
    },
    onError: (error, { id }) => update(id, { phase: "failed", error }),
  });

  const ask = useMutation({
    mutationFn: ({
      q,
      history,
      route,
    }: {
      id: number;
      q: string;
      history: AskTurn[];
      route?: "data";
    }) => {
      abort.current = new AbortController();
      return api.ask(
        {
          question: q,
          provider_id: chosen?.provider_id,
          start,
          end,
          sources: sources.length ? sources : undefined,
          history,
          tz: TZ,
          route,
        },
        abort.current.signal,
      );
    },
    onSuccess: (answer, { id, q, history }) => {
      const first = history[0]?.question ?? q;
      onAnswer?.({ sql: answer.sql, question: first });
      const auto = Boolean(answer.auto_run && answer.ask_id);
      const guidance = answer.route?.kind === "knowhow";
      setTurns((all) =>
        all.map((t) =>
          t.id === id
            ? {
                ...t,
                answer,
                phase: guidance ? "guidance" : auto ? "running" : "ready",
                askMs: Date.now() - (startedAt.current[id] ?? Date.now()),
              }
            : t,
        ),
      );
      if (auto && !guidance && answer.ask_id) run.mutate({ id, askId: answer.ask_id });
    },
    onError: (error, { id }) => update(id, { phase: "failed", error }),
  });
  const begin = (q: string, earlier: Turn[], route?: "data") => {
    const id = nextId.current++;
    startedAt.current[id] = Date.now();
    const history = earlier
      .filter((t) => t.answer)
      .slice(-MAX_TURNS)
      .map((t) => ({ question: t.question, sql: t.answer!.sql }));
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
    ask.mutate({ id, q, history, route });
  };
  const busy = ask.isPending || run.isPending || summarize.isPending;
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
    abort.current?.abort();
    setTurns([]);
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
    begin(
      t.question,
      turns.filter((x) => x.id !== t.id),
    );
  // Check your data instead (ADR-0042 condition 3): the same question as a data question.
  const checkData = (t: Turn) =>
    begin(
      t.question,
      turns.filter((x) => x.id !== t.id),
      "data",
    );
  const runTurn = (t: Turn) => t.answer?.ask_id && run.mutate({ id: t.id, askId: t.answer.ask_id });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex max-w-[880px] flex-col gap-2">
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
            <button
              type="submit"
              disabled={!question.trim() || busy}
              className={cn(
                "h-8 shrink-0 rounded px-4 font-semibold",
                question.trim() && !busy
                  ? "bg-accent text-on-accent hover:brightness-110"
                  : "border border-border-strong text-text-muted",
              )}
            >
              {turns.length ? "Refine" : "Ask"}
            </button>
          </div>
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
        <section aria-label="Library suggestions" className="flex flex-col gap-1.5 text-sm">
          <h3 className="font-semibold">Library queries that match your words</h3>
          {suggestions.data?.length ? (
            <ul className="flex flex-col gap-1.5">
              {suggestions.data.map((s) => (
                <li key={s.ref}>
                  <button
                    type="button"
                    onClick={() => onEdit?.(s.sql)}
                    className="font-semibold text-accent-text hover:underline"
                  >
                    {s.name}
                  </button>
                  <span className="block text-text-secondary">{s.why}</span>
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
      <ModelWait
        providerId={chosen?.provider_id ?? ""}
        label="Finding the right query"
        pending={ask.isPending}
        onCancel={() => abort.current?.abort()}
      />
      {turns.length ? (
        <div aria-label="Answers" className="mt-1 flex flex-col gap-4 border-t border-border pt-4">
          {/* Newest first, directly under the prompt that refines it (D256). */}
          {[...turns].reverse().map((t) => (
            <AskTurnBlock
              key={t.id}
              turn={t}
              start={start}
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
