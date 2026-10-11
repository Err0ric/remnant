import { useState, type FormEvent } from "react";
import type { CompiledSearch } from "@/lib/api";

interface SimplePanelProps {
  text: string;
  onText: (text: string) => void;
  onRun: () => void;
  /** The SQL behind the last Simple run, shown on request. */
  compiled: CompiledSearch | null;
  onEditAsSql: () => void;
  pending: boolean;
  /** Fields the search filters on that have no value anywhere in the time range. */
  emptyColumns?: string[];
}

const EXAMPLES = [
  'sshd "failed password"',
  "user:root -src_ip:10.*",
  "severity:>=high host:dc*",
  "EventID:4625",
];

/** Simple search (ADR-0009): one box, compiled to SQL on the server with no model. */
export function SimplePanel({
  text,
  onText,
  onRun,
  compiled,
  onEditAsSql,
  pending,
  emptyColumns = [],
}: SimplePanelProps) {
  const [showSql, setShowSql] = useState(false);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onRun();
  };
  return (
    <div id="search-panel-simple" role="tabpanel" aria-labelledby="search-tab-simple">
      <form aria-label="Simple search" onSubmit={submit} className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-2">
          <label htmlFor="simple-search" className="sr-only">
            Search text
          </label>
          <input
            id="simple-search"
            type="search"
            value={text}
            maxLength={2048}
            onChange={(e) => onText(e.target.value)}
            placeholder={`Words, "phrases", field:value, -field:value, OR, ( )`}
            spellCheck={false}
            autoComplete="off"
            className="h-9 min-w-0 flex-[1_1_320px] rounded border border-border-strong bg-inset px-3 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-focus-ring"
          />
          <button
            type="submit"
            disabled={pending}
            className="h-9 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
          >
            {pending ? "Searching…" : "Search"}
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-text-muted">
          <span>Try</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => onText(ex)}
              className="rounded px-1 font-mono text-accent-text hover:bg-surface-head"
            >
              {ex}
            </button>
          ))}
          <span className="ml-auto flex gap-3">
            <button
              type="button"
              aria-expanded={showSql}
              onClick={() => setShowSql((v) => !v)}
              disabled={!compiled}
              className="text-accent-text hover:underline disabled:text-text-muted disabled:no-underline"
            >
              {showSql ? "Hide SQL" : "Show SQL"}
            </button>
            <button
              type="button"
              onClick={onEditAsSql}
              disabled={!compiled}
              className="text-accent-text hover:underline disabled:text-text-muted disabled:no-underline"
            >
              Edit as SQL
            </button>
          </span>
        </div>
        {emptyColumns.length ? (
          <p role="status" className="text-sm text-warn">
            No event in this time range has a value in {emptyColumns.join(", ")}, so a filter on{" "}
            {emptyColumns.length === 1 ? "it" : "them"} matches nothing here. The parser for these
            sources may have left the value in the log text: search for it as words instead, for
            example &quot;203.0.113.9&quot; or -&quot;203.0.113.9&quot;.
          </p>
        ) : null}
        {compiled?.notes.length ? (
          <ul aria-label="Search notes" className="text-sm text-text-secondary">
            {compiled.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        ) : null}
        {showSql && compiled ? (
          <pre
            aria-label="SQL for this search"
            className="m-0 overflow-x-auto whitespace-pre-wrap rounded border border-border bg-inset px-3 py-2 font-mono text-sm"
          >
            {compiled.sql}
            {Object.keys(compiled.params).length
              ? `\n\n-- values, bound separately:\n${Object.entries(compiled.params)
                  .map(([k, v]) => `-- $${k} = ${JSON.stringify(v)}`)
                  .join("\n")}`
              : ""}
          </pre>
        ) : null}
      </form>
    </div>
  );
}
