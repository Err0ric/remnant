import { useQuery } from "@tanstack/react-query";
import { api, type QueryLibrary } from "@/lib/api";
import { sqlPlaceholders } from "@/lib/search";

const MAX = 6;

/** Example questions for Ask's empty state (owner, 2026-11-03; D182): one per library
 * query, taken from the queries the library offers this viewer (those whose sources had
 * events in the last 30 days), spread across packs, and only queries with no parameter
 * but the time range. Each is the query's own example question, preferring one that reads
 * as a question, so Ask routes it to that tested query. */
export function pickExamples(lib: QueryLibrary, max = MAX): string[] {
  const queues = lib.packs.map((p) =>
    p.queries
      .filter((q) => q.ask.length > 0)
      // As shipped: a parameter with a sample default (an address) still needs a value.
      .filter((q) => sqlPlaceholders(q.pack_sql).every((n) => n === "start" || n === "end"))
      .map((q) => q.ask.find((a) => a.trim().endsWith("?")) ?? (q.ask[0] as string)),
  );
  const out: string[] = [];
  for (let round = 0; out.length < max && queues.some((q) => q.length > round); round++) {
    for (const q of queues) {
      const next = q[round];
      if (next && !out.includes(next) && out.length < max) out.push(next);
    }
  }
  return out;
}

interface AskExamplesProps {
  onPick: (question: string) => void;
  disabled?: boolean;
}

/** Shown before the first question: a few that work on this install's own data. */
export function AskExamples({ onPick, disabled }: AskExamplesProps) {
  const lib = useQuery({ queryKey: ["library"], queryFn: api.library });
  const examples = lib.data ? pickExamples(lib.data) : [];
  if (!examples.length) return null;
  return (
    <section aria-label="Example questions" className="flex flex-col gap-1.5 text-sm">
      <h3 className="font-semibold">Try one of these on your data</h3>
      <ul className="flex flex-wrap gap-2">
        {examples.map((q) => (
          <li key={q}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onPick(q)}
              className="rounded border border-border-strong px-2.5 py-1 text-left hover:bg-surface-head disabled:opacity-40"
            >
              {q}
            </button>
          </li>
        ))}
      </ul>
      <p className="text-text-muted">Each matches a tested library query for your sources.</p>
    </section>
  );
}
