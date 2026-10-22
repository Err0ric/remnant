import { useMutation, useQuery } from "@tanstack/react-query";
import { ModelWait, isAborted, isModelBusy } from "@/components/ai/ModelWait";
import { useRef, useState } from "react";
import { LocalityBadge } from "@/features/providers/LocalityBadge";
import { ApiError, api } from "@/lib/api";
import { navigate } from "@/lib/route";
import { eventsSql, seedSearch } from "@/lib/searchSeed";
import { reportMarkdown } from "./report";

export const MAX_EXPLAIN = 50;

interface ExplainPanelProps {
  eventIds: string[];
  /** What the events are, for the report title ("Search results", a rule title). */
  subject: string;
  onClose: () => void;
}

function download(text: string, name: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/** Explain chosen events with a model; every claim shows the events it cites (rule 4). */
export function ExplainPanel({ eventIds, subject, onClose }: ExplainPanelProps) {
  const ids = eventIds.slice(0, MAX_EXPLAIN);
  const [provider, setProvider] = useState("");
  const [question, setQuestion] = useState("");
  const providers = useQuery({ queryKey: ["ask-providers"], queryFn: api.askProviders });
  const choices = providers.data ?? [];
  const chosen = provider || choices[0]?.provider_id || "";
  const abort = useRef<AbortController | null>(null);
  const run = useMutation({
    mutationFn: () => {
      abort.current = new AbortController();
      return api.explain(
        {
          event_ids: ids,
          provider_id: chosen || undefined,
          question: question.trim() || undefined,
        },
        abort.current.signal,
      );
    },
  });
  const answer = run.data;

  return (
    <section
      aria-label="Explain events"
      className="flex flex-col gap-2 rounded-card border border-border bg-surface p-3 text-sm"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">
          Explain {ids.length} {ids.length === 1 ? "event" : "events"}
        </span>
        {eventIds.length > MAX_EXPLAIN ? (
          <span className="text-text-secondary">(the first {MAX_EXPLAIN} only)</span>
        ) : null}
        <button
          type="button"
          className="ml-auto rounded px-2 py-1 hover:bg-surface-head"
          onClick={onClose}
        >
          Close
        </button>
      </div>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          run.mutate();
        }}
      >
        <label className="flex flex-col gap-1">
          <span className="text-text-secondary">Model</span>
          <select
            aria-label="Model"
            className="h-8 rounded border border-border bg-surface px-1"
            value={chosen}
            onChange={(e) => setProvider(e.target.value)}
          >
            {choices.map((p) => (
              <option key={p.provider_id} value={p.provider_id}>
                {p.name} · {p.model} · {p.locality === "local" ? "Local" : "Cloud"}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-0 flex-[1_1_260px] flex-col gap-1">
          <span className="text-text-secondary">Question (optional)</span>
          <input
            className="h-8 rounded border border-border bg-inset px-2"
            maxLength={500}
            value={question}
            placeholder="What happened here?"
            onChange={(e) => setQuestion(e.target.value)}
          />
        </label>
        <button
          type="submit"
          className="h-8 rounded bg-accent px-3 font-semibold text-white disabled:opacity-40"
          disabled={!ids.length || !choices.length || run.isPending}
        >
          {run.isPending ? "Explaining…" : "Explain"}
        </button>
      </form>
      {providers.isSuccess && !choices.length ? (
        <p className="text-text-secondary">No AI provider is enabled. An admin can add one.</p>
      ) : null}
      <p className="text-text-muted">
        Only these events are sent, and only from sources you can read. Cloud models are refused for
        local-only sources.
      </p>
      <ModelWait
        providerId={chosen}
        label="Explaining"
        pending={run.isPending}
        onCancel={() => abort.current?.abort()}
      />
      {run.error && isAborted(run.error) ? (
        <p role="status" className="text-text-muted">
          Cancelled.
        </p>
      ) : run.error && isModelBusy(run.error) ? (
        <p role="alert" className="flex flex-wrap items-center gap-3 text-warn">
          {run.error.message}
          <button
            type="button"
            onClick={() => run.mutate()}
            className="h-7 rounded border border-border-strong px-3 text-text hover:bg-surface-head"
          >
            Retry
          </button>
        </p>
      ) : run.error ? (
        <p role="alert" className="text-danger">
          {run.error instanceof ApiError ? run.error.message : "That did not work"}
        </p>
      ) : null}
      {answer ? (
        <div className="flex flex-col gap-2 border-t border-border pt-2">
          <div className="flex flex-wrap items-center gap-2 text-text-secondary">
            <LocalityBadge locality={answer.provider.locality} />
            <span>
              {answer.provider.name} · {answer.provider.model}
            </span>
            <span>·</span>
            <span className={answer.citation_check === "pass" ? "text-ok" : "text-warn"}>
              {answer.citation_check === "pass"
                ? "Every claim cites events that were sent"
                : "Some claims are unverified"}
            </span>
            {answer.not_found ? (
              <span>· {answer.not_found} not found or not readable, not sent</span>
            ) : null}
          </div>
          <ol aria-label="Claims" className="m-0 flex list-decimal flex-col gap-2 pl-5">
            {answer.claims.map((c, i) => (
              <li key={i}>
                {c.verified ? null : (
                  <span className="mr-1.5 rounded-badge bg-sev-medium-bg px-1.5 py-px text-xs text-sev-medium-text">
                    unverified
                  </span>
                )}
                <span>{c.text}</span>
                <div className="mt-0.5 flex flex-wrap gap-1">
                  {c.event_ids.map((id) => (
                    <span
                      key={id}
                      className={`rounded-badge px-1.5 py-px font-mono text-xs ${answer.events_sent.includes(id) ? "bg-sev-info-bg text-text-secondary" : "bg-sev-critical-bg text-sev-critical-text"}`}
                      title={
                        answer.events_sent.includes(id) ? "Sent" : "Not one of the events sent"
                      }
                    >
                      {id.slice(0, 8)}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ol>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="h-8 rounded border border-border px-3 text-accent-text hover:bg-surface-head"
              onClick={() => {
                const cited = answer.claims.flatMap((c) => c.event_ids);
                seedSearch({
                  sql: eventsSql(cited.filter((id) => answer.events_sent.includes(id))),
                });
                navigate("search");
              }}
            >
              Open cited events in Search
            </button>
            <button
              type="button"
              className="h-8 rounded border border-border px-3 hover:bg-surface-head"
              onClick={() =>
                download(reportMarkdown(answer, `Explanation: ${subject}`), "explanation-report.md")
              }
            >
              Download report (Markdown)
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
