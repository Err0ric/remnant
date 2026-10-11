import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ResultsTable } from "@/features/search/ResultsTable";
import { ApiError, api, type SavedSearch } from "@/lib/api";
import { TIME_RANGES, rangeStart, type TimeRangeId } from "@/lib/search";

interface SearchRunnerProps {
  search: SavedSearch;
  onClose: () => void;
}

// Saved searches always run over a bounded window ({{start}} and {{end}}), so no "All time".
const RANGES = TIME_RANGES.filter((r) => r.id !== "all");

/** Run a saved search with your own source access. Parameters start at their defaults. */
export function SearchRunner({ search, onClose }: SearchRunnerProps) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      search.params.map((p) => [
        p.name,
        p.default === undefined || p.default === null ? "" : String(p.default),
      ]),
    ),
  );
  const [range, setRange] = useState<TimeRangeId>("24h");
  const run = useMutation({
    mutationFn: () => {
      const params = Object.fromEntries(Object.entries(values).filter(([, v]) => v !== ""));
      return api.runSearch(search.id, { params, start: rangeStart(range) });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run.mutate();
  };

  return (
    <section
      aria-label={`Run ${search.name}`}
      className="rounded-card border border-border bg-surface"
    >
      <form onSubmit={submit} className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-baseline gap-2">
          <h2 className="text-base font-semibold">{search.name}</h2>
          <span className="font-mono text-sm text-text-muted">{search.id}</span>
          <button type="button" onClick={onClose} className="ml-auto text-sm text-text-secondary">
            Close
          </button>
        </div>
        {search.description ? (
          <p className="text-sm text-text-secondary">{search.description}</p>
        ) : null}
        <pre className="overflow-x-auto rounded border border-border bg-inset p-3 font-mono text-sm text-text">
          {search.sql}
        </pre>
        <div className="flex flex-wrap items-end gap-3">
          {search.params.map((p) => (
            <label key={p.name} className="flex flex-col gap-1 text-sm">
              <span className="font-semibold">
                <span className="font-mono">{p.name}</span>{" "}
                <span className="font-normal text-text-muted">({p.type})</span>
              </span>
              {p.type === "bool" ? (
                <select
                  aria-label={p.name}
                  value={values[p.name] ?? ""}
                  onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
                  className="h-8 rounded border border-border-strong bg-inset px-2"
                >
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              ) : (
                <input
                  aria-label={p.name}
                  value={values[p.name] ?? ""}
                  onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
                  inputMode={p.type === "int" || p.type === "float" ? "decimal" : undefined}
                  className="h-8 w-48 rounded border border-border-strong bg-inset px-2 font-mono"
                />
              )}
            </label>
          ))}
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-semibold">Time range</span>
            <select
              aria-label="Time range"
              value={range}
              onChange={(e) => setRange(e.target.value as TimeRangeId)}
              className="h-8 rounded border border-border-strong bg-inset px-2"
            >
              {RANGES.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            disabled={run.isPending}
            className="h-8 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
          >
            {run.isPending ? "Running" : "Run"}
          </button>
        </div>
        {run.error ? (
          <p role="alert" className="text-sm text-danger">
            {run.error instanceof ApiError ? run.error.message : "Run failed"}
          </p>
        ) : null}
      </form>
      {run.data ? (
        <div className="border-t border-border">
          <ResultsTable result={run.data} view="parsed" />
        </div>
      ) : null}
    </section>
  );
}
