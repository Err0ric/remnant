import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { ModelWait } from "@/components/ai/ModelWait";
import { api, type AskTurn } from "@/lib/api";
import { setAskProvider, useAskProvider } from "@/lib/askProvider";
import { navigate } from "@/lib/route";
import { AskTurnBlock, type Turn } from "./AskTurnBlock";

const MAX_TURNS = 3;

interface AskThreadProps {
  start: string | undefined;
  sources: string[];
  isAdmin: boolean;
  /** A question to start with (the slide-over opened from the command palette). */
  initialQuestion?: string;
  /** Opens a turn's SQL in the SQL editor. */
  onEdit?: (sql: string) => void;
  /** The latest SQL and the first question, for Save; null after New question. */
  onAnswer?: (answer: { sql: string; question: string } | null) => void;
  /** The AI switch, at the start of the question box (Search page). */
  toggle?: ReactNode;
  /** Focus the question box on open (the slide-over). */
  autoFocus?: boolean;
}

/**
 * Ask (ADR-0042 slice 1a): a question becomes SQL that runs at once when it passes the
 * guard on the asker's own sources, unless the install keeps click-to-run. Each turn is a
 * block; follow-ups stack below and refine the last answer (3 turns).
 */
export function AskThread({
  start,
  sources,
  isAdmin,
  initialQuestion = "",
  onEdit,
  onAnswer,
  toggle,
  autoFocus,
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

  const run = useMutation({
    mutationFn: ({ askId }: { id: number; askId: string }) => {
      abort.current = new AbortController();
      return api.runAnswer(askId, abort.current.signal);
    },
    onMutate: ({ id }) => update(id, { phase: "running" }),
    onSuccess: (result, { id }) => update(id, { phase: "done", result, runMs: result.elapsed_ms }),
    onError: (error, { id }) => update(id, { phase: "failed", error }),
  });

  const ask = useMutation({
    mutationFn: ({ q, history }: { id: number; q: string; history: AskTurn[] }) => {
      abort.current = new AbortController();
      return api.ask(
        {
          question: q,
          provider_id: chosen?.provider_id,
          start,
          sources: sources.length ? sources : undefined,
          history,
        },
        abort.current.signal,
      );
    },
    onSuccess: (answer, { id, q, history }) => {
      const first = history[0]?.question ?? q;
      onAnswer?.({ sql: answer.sql, question: first });
      const auto = Boolean(answer.auto_run && answer.ask_id);
      setTurns((all) =>
        all.map((t) =>
          t.id === id
            ? {
                ...t,
                answer,
                phase: auto ? "running" : "ready",
                askMs: Date.now() - (startedAt.current[id] ?? Date.now()),
              }
            : t,
        ),
      );
      if (auto && answer.ask_id) run.mutate({ id, askId: answer.ask_id });
    },
    onError: (error, { id }) => update(id, { phase: "failed", error }),
  });
  const begin = (q: string, earlier: Turn[]) => {
    const id = nextId.current++;
    startedAt.current[id] = Date.now();
    const history = earlier
      .filter((t) => t.answer)
      .slice(-MAX_TURNS)
      .map((t) => ({ question: t.question, sql: t.answer!.sql }));
    setTurns([...earlier, { id, question: q, phase: "finding" }]);
    ask.mutate({ id, q, history });
  };
  const busy = ask.isPending || run.isPending;
  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const q = question.trim();
    if (!q || busy || noProviders) return;
    setQuestion("");
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
  const retry = (t: Turn) =>
    begin(
      t.question,
      turns.filter((x) => x.id !== t.id),
    );
  const runTurn = (t: Turn) => t.answer?.ask_id && run.mutate({ id: t.id, askId: t.answer.ask_id });

  return (
    <div className="flex flex-col gap-3">
      <form aria-label="Ask a question" onSubmit={submit} className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label htmlFor="ask-provider" className="text-text-secondary">
            Model
          </label>
          <select
            id="ask-provider"
            value={chosen?.provider_id ?? ""}
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
          {chosen ? (
            chosen.locality === "cloud" ? (
              <span className="rounded-badge bg-cloud-bg px-2 py-px text-xs text-cloud-text">
                Cloud
              </span>
            ) : (
              <span className="rounded-badge bg-local-bg px-2 py-px text-xs text-local-text">
                Local
              </span>
            )
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
        <label htmlFor="ask-question" className="sr-only">
          Question
        </label>
        <div className="flex items-start gap-2">
          {toggle}
          <textarea
            id="ask-question"
            rows={3}
            maxLength={2000}
            // The slide-over opens with the cursor in the box (it is the whole panel).
            autoFocus={autoFocus}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={
              turns.length
                ? "Refine the last answer: only failures, by host, for alice"
                : "How many failed logins on the firewall today? Or paste a KQL or SPL query."
            }
            className="min-w-0 flex-1 rounded border border-accent bg-inset px-3 py-2.5 text-base focus:outline-none focus:ring-2 focus:ring-focus-ring"
          />
        </div>
        {chosen?.locality === "cloud" ? (
          <p role="note" className="text-sm text-cloud-text">
            Your question is sent to {chosen.name}.
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={!question.trim() || busy || noProviders}
            className="h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head disabled:opacity-40"
          >
            {turns.length ? "Refine" : "Ask"}
          </button>
          <span className="text-sm text-text-muted">
            Ctrl+Enter to ask · the query runs on your own sources; its SQL is under How I got this
          </span>
        </div>
      </form>
      <ModelWait
        providerId={chosen?.provider_id ?? ""}
        label="Finding the right query"
        pending={ask.isPending}
        onCancel={() => abort.current?.abort()}
      />
      {turns.length ? (
        <div aria-label="Answers" className="flex flex-col gap-4">
          {turns.map((t) => (
            <AskTurnBlock key={t.id} turn={t} onRun={runTurn} onRetry={retry} onEdit={onEdit} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
