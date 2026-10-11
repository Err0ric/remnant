import type { AskResponse } from "@/lib/api";

interface AnswerPanelProps {
  answer: AskResponse;
}

const CHECK: Record<AskResponse["check"], { label: string; tone: string }> = {
  ok: { label: "Checked: the query runs and returns rows", tone: "text-ok" },
  empty: { label: "Checked: the query runs but matched no rows", tone: "text-warn" },
  failed: { label: "Check failed", tone: "text-danger" },
};

/**
 * What the model said about its SQL. Model text can be steered by log content, so it is
 * rendered as plain text, labelled as model output, and never linked or interpreted.
 */
export function AnswerPanel({ answer }: AnswerPanelProps) {
  const check = CHECK[answer.check];
  return (
    <section
      aria-label="Model explanation"
      className="flex flex-col gap-2 rounded-card border border-border bg-surface px-3.5 py-3 text-sm"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-semibold">Model explanation</span>
        <span className="text-text-muted">
          {answer.provider.name} · {answer.provider.model} ·{" "}
          {answer.attempts === 1 ? "1 attempt" : `${answer.attempts} attempts`}
        </span>
        <span className={`ml-auto font-semibold ${check.tone}`}>{check.label}</span>
      </div>
      {answer.check === "failed" && answer.check_detail ? (
        <p className="font-mono text-sev-critical-text">{answer.check_detail}</p>
      ) : null}
      {answer.explanation ? <p className="text-text">{answer.explanation}</p> : null}
      {answer.assumptions.length ? (
        <div>
          <div className="text-text-secondary">Assumptions</div>
          <ul className="ml-5 list-disc text-text">
            {answer.assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="text-text-muted">
        Written by a model. Read the SQL before running it; nothing runs until you choose Run query.
      </p>
    </section>
  );
}
