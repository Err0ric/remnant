import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { ApiError, api, type AskResponse, type AskTurn } from "@/lib/api";
import { navigate } from "@/lib/route";
import { setAskProvider, useAskProvider } from "@/lib/askProvider";
import { AnswerPanel } from "@/features/ask/AnswerPanel";

const MAX_TURNS = 3;

interface AskPanelProps {
  start: string | undefined;
  sources: string[];
  isAdmin: boolean;
  /** Copies the SQL into the SQL tab's editor and runs it there (ADR-0008 row 2). */
  onRun: (sql: string) => void;
  /** The latest generated SQL and the first question, for Save; null after New question. */
  onAnswer: (answer: { sql: string; question: string } | null) => void;
  pending: boolean;
  /** The AI switch, shown at the start of the question box. */
  toggle?: ReactNode;
}

function askError(err: unknown): string {
  if (!(err instanceof ApiError)) return "The question could not be answered";
  if (err.code === "classification_blocked")
    return `${err.message}. Choose a local provider, or filter to cloud-allowed sources.`;
  return err.message;
}

/**
 * Ask in plain English (SPEC 5.3): a question becomes SQL shown for review. Nothing runs
 * until the analyst clicks Run. Follow-ups refine the same conversation (last 3 turns).
 * Pasted Kusto KQL or SPL is a fair question too: the model translates it (ADR-0009).
 */
export function AskPanel({
  start,
  sources,
  isAdmin,
  onRun,
  onAnswer,
  pending,
  toggle,
}: AskPanelProps) {
  const providerId = useAskProvider();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<AskTurn[]>([]);
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const providers = useQuery({ queryKey: ["ask-providers"], queryFn: api.askProviders });
  // The remembered choice, while that provider is still enabled; else the first one.
  const chosen =
    providers.data?.find((p) => p.provider_id === providerId)?.provider_id ??
    providers.data?.[0]?.provider_id ??
    "";

  const ask = useMutation({
    mutationFn: (q: string) =>
      api.ask({
        question: q,
        provider_id: chosen || undefined,
        start,
        sources: sources.length ? sources : undefined,
        history: turns.slice(-MAX_TURNS),
      }),
    onSuccess: (res, q) => {
      setAnswer(res);
      const next = [...turns, { question: q, sql: res.sql }].slice(-MAX_TURNS);
      setTurns(next);
      setQuestion("");
      onAnswer({ sql: res.sql, question: next[0]?.question ?? q });
    },
  });

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const q = question.trim();
    if (q && !ask.isPending) ask.mutate(q);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submit();
  };
  const startOver = () => {
    setTurns([]);
    setAnswer(null);
    ask.reset();
    onAnswer(null);
  };
  const noProviders = providers.isSuccess && providers.data.length === 0;
  // Local models can take a while; show that something is happening.
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!ask.isPending) return;
    setElapsed(0);
    const started = Date.now();
    const timer = window.setInterval(
      () => setElapsed(Math.round((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [ask.isPending]);

  return (
    <div className="flex flex-col gap-2.5">
      <form aria-label="Ask a question" onSubmit={submit} className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label htmlFor="ask-provider" className="text-text-secondary">
            Model
          </label>
          <select
            id="ask-provider"
            value={chosen}
            onChange={(e) => setAskProvider(e.target.value)}
            disabled={!providers.data?.length}
            className="h-8 rounded border border-border-strong bg-surface px-2 text-sm"
          >
            {providers.data?.length ? null : <option value="">None enabled</option>}
            {(providers.data ?? []).map((p) => (
              <option key={p.provider_id} value={p.provider_id}>
                {p.name} · {p.model} · {p.locality === "local" ? "Local" : "Cloud"}
              </option>
            ))}
          </select>
          {providers.data?.find((p) => p.provider_id === chosen)?.locality === "cloud" ? (
            <span className="rounded-badge bg-cloud-bg px-2 py-px text-xs text-cloud-text">
              Cloud: local-only sources are blocked
            </span>
          ) : chosen ? (
            <span className="rounded-badge bg-local-bg px-2 py-px text-xs text-local-text">
              Local
            </span>
          ) : null}
          {turns.length ? (
            <button
              type="button"
              onClick={startOver}
              className="ml-auto rounded px-2 py-1 text-accent-text hover:bg-surface-head"
            >
              New question
            </button>
          ) : null}
        </div>
        {noProviders ? (
          <p className="text-sm text-text-secondary">
            No AI provider is set up. Simple and SQL searches work without one.
            {isAdmin ? (
              <>
                {" "}
                <button
                  type="button"
                  onClick={() => navigate("providers")}
                  className="text-accent-text hover:underline"
                >
                  Add one under AI providers
                </button>
              </>
            ) : (
              " An administrator can add one."
            )}
          </p>
        ) : null}
        {turns.length ? (
          <ol
            aria-label="Earlier questions"
            className="ml-5 list-decimal text-sm text-text-secondary"
          >
            {turns.map((t, i) => (
              <li key={i}>{t.question}</li>
            ))}
          </ol>
        ) : null}
        <label htmlFor="ask-question" className="sr-only">
          Question
        </label>
        <div className="flex items-start gap-2">
          {toggle}
          <textarea
            id="ask-question"
            rows={2}
            maxLength={2000}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={
              turns.length
                ? "Refine it: show me these for alice, break that down by host, count them"
                : "Which source IPs had the most failed SSH logins? Or paste a KQL or SPL query to translate."
            }
            className="min-w-0 flex-1 rounded border border-accent bg-inset px-3 py-2 text-base focus:outline-none focus:ring-2 focus:ring-focus-ring"
          />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={!question.trim() || ask.isPending || noProviders}
            className="h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head disabled:opacity-40"
          >
            {ask.isPending
              ? `Writing SQL… ${elapsed ? `${elapsed} s` : ""}`.trim()
              : turns.length
                ? "Refine"
                : "Ask"}
          </button>
          <span className="text-sm text-text-muted">
            Ctrl+Enter to ask · the model writes SQL; you decide whether to run it
          </span>
        </div>
      </form>

      {ask.isError ? (
        <div
          role="alert"
          className="rounded border border-danger bg-sev-critical-bg px-3 py-2 text-sm text-sev-critical-text"
        >
          {askError(ask.error)}
        </div>
      ) : null}

      {answer ? (
        <>
          <div>
            <div className="mb-1 text-sm text-text-secondary">Generated SQL</div>
            <pre
              aria-label="Generated SQL"
              className="m-0 overflow-x-auto whitespace-pre-wrap rounded border border-border bg-inset px-3 py-2 font-mono text-sm"
            >
              {answer.sql}
            </pre>
          </div>
          <div className="flex flex-wrap items-center gap-4 text-sm text-text-muted">
            <button
              type="button"
              onClick={() => onRun(answer.sql)}
              disabled={pending}
              className="h-8 rounded border border-accent px-4 text-sm font-semibold text-accent-text hover:bg-accent-subtle disabled:opacity-60"
            >
              {pending ? "Running…" : "Run"}
            </button>
            <span>Run copies this SQL to the SQL tab, where you can edit it, and runs it</span>
          </div>
          <AnswerPanel answer={answer} />
        </>
      ) : null}
    </div>
  );
}
