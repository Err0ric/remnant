import { useState } from "react";
import { ExplainPanel } from "@/features/explain/ExplainPanel";
import { api, type QueryRequest, type QueryResult } from "@/lib/api";
import { ColumnChooser } from "./ColumnChooser";
import { HandoffPanel } from "./HandoffPanel";
import { ResultsTable } from "./ResultsTable";

const DENSITY_KEY = "results-density";
const GEO_KEY = "results-location";

function storedGeo(): boolean {
  try {
    return window.localStorage.getItem(GEO_KEY) !== "hidden";
  } catch {
    return true;
  }
}

function storedCompact(): boolean {
  try {
    return window.localStorage.getItem(DENSITY_KEY) === "compact";
  } catch {
    return false; // storage blocked: default to comfortable rows
  }
}

interface ResultsCardProps {
  result: QueryResult | undefined;
  pending: boolean;
  /** Changes on every run so the table resets paging and expansion. */
  runKey: string;
  /** Admins and analysts may send chosen events to a model (auditors have no AI). */
  canExplain?: boolean;
}

/** Download the CSV the server produced (and audited) for the query that was run. */
export async function downloadCsv(body: QueryRequest) {
  const csv = await api.exportCsv(body);
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "search-results.csv";
  a.click();
  URL.revokeObjectURL(url);
}

/** Results with the parsed/raw toggle, shared by Search and Ask. */
export function ResultsCard({ result, pending, runKey, canExplain = false }: ResultsCardProps) {
  // Selection for Explain is per run: a new query starts it again.
  const [selection, setSelection] = useState<{ key: string; ids: Set<string> }>({
    key: runKey,
    ids: new Set(),
  });
  const selected = selection.key === runKey ? selection.ids : new Set<string>();
  const [explaining, setExplaining] = useState<string[] | null>(null);
  const [sending, setSending] = useState<string[] | null>(null);
  const idIndex = result?.columns.indexOf("event_id") ?? -1;
  const explainable = canExplain && idIndex >= 0 && (result?.rows.length ?? 0) > 0;
  const toggleSelect = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelection({ key: runKey, ids: next });
  };
  const [view, setView] = useState<"parsed" | "raw">("parsed");
  // Kept across runs, by name: a column hidden once stays hidden while it exists.
  const [hidden, setHidden] = useState<string[]>([]);
  const [choosing, setChoosing] = useState(false);
  const [compact, setCompact] = useState(storedCompact);
  const [showGeo, setShowGeo] = useState(storedGeo);
  const hasGeo = Object.keys(result?.geo ?? {}).length > 0;
  const toggleGeo = () => {
    const next = !showGeo;
    setShowGeo(next);
    try {
      window.localStorage.setItem(GEO_KEY, next ? "shown" : "hidden");
    } catch {
      // storage blocked: the choice lasts for this page only
    }
  };
  const toggleCompact = () => {
    const next = !compact;
    setCompact(next);
    try {
      window.localStorage.setItem(DENSITY_KEY, next ? "compact" : "comfortable");
    } catch {
      // A convenience only; the toggle still works for this page.
    }
  };
  const columns = (result?.columns ?? []).filter((c) => c !== "event_id");
  return (
    <section
      aria-label="Results"
      className="min-w-0 flex-1 rounded border border-border bg-surface"
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3.5 py-2.5">
        <span className="font-semibold">Results</span>
        <span className="text-sm text-text-secondary">
          {result
            ? `${result.row_count.toLocaleString()}${result.truncated ? "+" : ""} ${result.row_count === 1 ? "item" : "items"}${result.truncated ? " (limit reached; narrow the search to see the rest)" : ""}${result.sources.length ? ` · ${result.sources.length} ${result.sources.length === 1 ? "source" : "sources"}` : ""}`
            : pending
              ? "Running…"
              : ""}
        </span>
        <span className="ml-auto flex items-center gap-3">
          {explainable && result ? (
            <button
              type="button"
              className="text-sm font-semibold text-accent-text hover:underline"
              title={
                selected.size
                  ? "Explain the events you selected"
                  : "Select events in their details, or explain the first 50 rows"
              }
              onClick={() =>
                setExplaining(
                  selected.size
                    ? [...selected]
                    : result.rows.slice(0, 50).map((r) => String(r[idIndex])),
                )
              }
            >
              {selected.size ? `Explain ${selected.size} selected` : "Explain"}
            </button>
          ) : null}
          {explainable && selected.size ? (
            <button
              type="button"
              className="text-sm font-semibold text-accent-text hover:underline"
              title="Send the selected events to a ticket system, chat, or mailbox"
              onClick={() => {
                setExplaining(null);
                setSending([...selected]);
              }}
            >
              Send {selected.size}
            </button>
          ) : null}
          {view === "parsed" ? (
            <>
              <span className="text-sm text-text-muted">Click a row to expand it</span>
              <button
                type="button"
                aria-pressed={choosing}
                aria-expanded={choosing}
                onClick={() => setChoosing(!choosing)}
                disabled={!columns.length}
                className="text-sm text-text-secondary hover:text-text disabled:opacity-40"
              >
                Columns{hidden.some((h) => columns.includes(h)) ? " (some hidden)" : ""}
              </button>
              {hasGeo ? (
                <button
                  type="button"
                  aria-pressed={showGeo}
                  onClick={toggleGeo}
                  title="Country and network of public addresses, from the local GeoIP files"
                  className="text-sm text-text-secondary hover:text-text"
                >
                  Location
                </button>
              ) : null}
              <button
                type="button"
                aria-pressed={compact}
                onClick={toggleCompact}
                className="text-sm text-text-secondary hover:text-text"
              >
                Compact
              </button>
            </>
          ) : null}
          <span
            role="group"
            aria-label="Results view"
            className="flex rounded border border-border-strong"
          >
            {(["parsed", "raw"] as const).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                onClick={() => setView(v)}
                className={
                  view === v
                    ? "bg-accent-subtle px-2.5 py-0.5 text-sm font-semibold text-accent-text"
                    : "px-2.5 py-0.5 text-sm text-text-secondary hover:text-text"
                }
              >
                {v === "parsed" ? "Parsed" : "Raw"}
              </button>
            ))}
          </span>
        </span>
      </div>
      {choosing && view === "parsed" && columns.length ? (
        <ColumnChooser columns={columns} hidden={hidden} onChange={setHidden} />
      ) : null}
      {sending ? (
        <HandoffPanel key={sending.join(",")} eventIds={sending} onClose={() => setSending(null)} />
      ) : null}
      {explaining ? (
        <div className="border-b border-border px-3.5 py-3">
          <ExplainPanel
            key={explaining.join(",")}
            eventIds={explaining}
            subject="search results"
            onClose={() => setExplaining(null)}
          />
        </div>
      ) : null}
      {result ? (
        <ResultsTable
          key={runKey}
          result={result}
          view={view}
          hidden={hidden}
          compact={compact}
          geo={showGeo ? result.geo : undefined}
          selected={explainable ? selected : undefined}
          onToggleSelect={explainable ? toggleSelect : undefined}
        />
      ) : null}
    </section>
  );
}
