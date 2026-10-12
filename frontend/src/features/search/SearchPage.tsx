import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Command, PageHeader } from "@/components/shell/PageHeader";
import { api, type CompiledSearch, type QueryRequest, type QueryResult } from "@/lib/api";
import { DEFAULT_SQL, rangeStart, type TimeRangeId } from "@/lib/search";
import { navigate } from "@/lib/route";
import { seedSchedule } from "@/lib/scheduleSeed";
import { RUN_SEARCH_EVENT, takeSearchSeed } from "@/lib/searchSeed";
import {
  addTerm,
  filterTerm,
  inlineParams,
  storeTab,
  storedTab,
  type SearchTab,
} from "@/lib/simpleSearch";
import { AskPanel } from "./AskPanel";
import { FieldActionsContext, type FieldActions } from "./fieldActions";
import { FilterBar } from "./FilterBar";
import { downloadCsv, ResultsCard } from "./ResultsCard";
import { SaveSearchForm } from "./SaveSearchForm";
import { SearchTabs } from "./SearchTabs";
import { SimplePanel } from "./SimplePanel";
import { SqlEditor } from "./SqlEditor";

interface SearchPageProps {
  /** Admins and analysts author saved searches; auditors are read-only (SPEC 3.6). */
  canSave: boolean;
  /** Admins and analysts may ask a model; auditors have no Ask. */
  canAsk?: boolean;
  isAdmin?: boolean;
  /** /ask opens the Ask tab (ADR-0008). */
  initialTab?: SearchTab;
}

type Run = Pick<QueryRequest, "sql" | "params">;
// Field actions apply to text, number, and true/false columns; never to the raw line.
const ACTION_TYPES = new Set(["string", "int", "bool"]);
const NO_ACTIONS = new Set(["raw"]);

const ALERT =
  "rounded border border-danger bg-sev-critical-bg px-3 py-2 text-sm text-sev-critical-text";

/**
 * Search (ADR-0008, ADR-0009): Simple, Ask in plain English, and SQL write the query; one
 * results table shows it. Everything runs through /api/query, its guard, and its audit.
 */
export function SearchPage({
  canSave,
  canAsk = false,
  isAdmin = false,
  initialTab,
}: SearchPageProps) {
  // A handoff from another page (rule matches) opens on the SQL tab over all time.
  const [seed] = useState(takeSearchSeed);
  const sqlSeed = seed?.sql !== undefined;
  const [tabState, setTabState] = useState<SearchTab>(() =>
    sqlSeed ? "sql" : (initialTab ?? storedTab()),
  );
  const tab: SearchTab = tabState === "ask" && !canAsk ? "simple" : tabState;
  const setTab = (t: SearchTab) => {
    setTabState(t);
    storeTab(t);
  };
  const [text, setText] = useState("");
  // The last compiled Simple search and the text it came from (saved as the origin).
  const [compiled, setCompiled] = useState<(CompiledSearch & { text: string }) | null>(null);
  const [sql, setSql] = useState(seed?.sql ?? DEFAULT_SQL);
  const [askAnswer, setAskAnswer] = useState<{ sql: string; question: string } | null>(null);
  const [range, setRange] = useState<TimeRangeId>(sqlSeed ? "all" : "24h");
  const [sources, setSources] = useState<string[]>(seed?.sources ?? []);
  const [lastRun, setLastRun] = useState<Date | null>(null);
  const [saving, setSaving] = useState(false);
  // Schedule saves first (a schedule runs a saved search), then opens the schedule form.
  const [scheduleAfterSave, setScheduleAfterSave] = useState(false);
  const [savedId, setSavedId] = useState<string | null>(null);
  const schema = useQuery({
    queryKey: ["schema-columns"],
    queryFn: api.columns,
    staleTime: Infinity,
  });
  const columnNames = useMemo(() => (schema.data ?? []).map((c) => c.name), [schema.data]);

  // The request behind the table on screen; exports repeat exactly it, on the server.
  const lastRequest = useRef<QueryRequest | null>(null);
  const run = useMutation({
    mutationFn: (req: Run) => {
      const body: QueryRequest = {
        ...req,
        start: rangeStart(range),
        sources: sources.length ? sources : undefined,
      };
      lastRequest.current = body;
      return api.query(body);
    },
    onSuccess: () => setLastRun(new Date()),
  });
  const simple = useMutation({
    mutationFn: (v: { text: string; top?: string }) => api.compileSearch(v.text, v.top),
    onSuccess: (c, v) => {
      if (!v.top) setCompiled({ ...c, text: v.text });
      run.mutate({ sql: c.sql, params: c.params });
    },
  });
  const exporter = useMutation({ mutationFn: downloadCsv });
  // Fields a Simple search filters on that have no value anywhere in the scope: a filter
  // on them silently matches nothing (often because a generic parser left the value in
  // the raw line). One count per column, through the same guarded query path.
  const filtered = (compiled?.columns ?? []).filter((c) => /^[a-z_]{1,64}$/.test(c));
  const coverage = useQuery({
    queryKey: ["field-coverage", filtered, range, sources, lastRun?.getTime()],
    enabled: tab === "simple" && filtered.length > 0 && run.isSuccess,
    queryFn: () =>
      api.query({
        sql: `SELECT ${filtered.map((c) => `count("${c}") AS "${c}"`).join(", ")} FROM events`,
        start: rangeStart(range),
        sources: sources.length ? sources : undefined,
      }),
    staleTime: 60_000,
  });
  const emptyColumns =
    coverage.data?.rows[0] !== undefined
      ? coverage.data.columns.filter((_, i) => Number(coverage.data?.rows[0]?.[i] ?? 0) === 0)
      : [];
  const result: QueryResult | undefined = run.data;
  const pending = run.isPending || simple.isPending;

  const runSql = (value: string) => run.mutate({ sql: value });
  const runAsk = (value: string) => {
    setSql(value); // the editor always holds what produced the results
    runSql(value);
  };
  const runCurrent = () => {
    if (tab === "simple") simple.mutate({ text });
    else if (tab === "sql") runSql(sql);
    else if (askAnswer) runAsk(askAnswer.sql);
  };

  // Run once on open so the page shows recent events immediately.
  useEffect(() => {
    if (sqlSeed || tab === "sql") runSql(sql);
    else simple.mutate({ text: "" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // "Run" from the command palette runs whatever this page shows.
  const runLatest = useRef(runCurrent);
  runLatest.current = runCurrent;
  useEffect(() => {
    const onRun = () => runLatest.current();
    window.addEventListener(RUN_SEARCH_EVENT, onRun);
    return () => window.removeEventListener(RUN_SEARCH_EVENT, onRun);
  }, []);

  const actions = useMemo<FieldActions>(
    () => ({
      fields: new Set(
        (schema.data ?? [])
          .filter((c) => ACTION_TYPES.has(c.type) && !NO_ACTIONS.has(c.name))
          .map((c) => c.name),
      ),
      filter: (field, value, exclude) => {
        const next = addTerm(text, filterTerm(field, value, exclude));
        setText(next);
        setTab("simple");
        simple.mutate({ text: next });
      },
      top: (field) => {
        setTab("simple");
        simple.mutate({ text, top: field });
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [schema.data, text],
  );

  // What Save and Schedule store: the SQL behind the active tab, values written in.
  const sqlToSave =
    tab === "simple"
      ? compiled
        ? inlineParams(compiled)
        : DEFAULT_SQL
      : tab === "ask"
        ? (askAnswer?.sql ?? "")
        : sql;

  const meta = lastRun
    ? `Last run ${lastRun.toISOString().slice(11, 19)} UTC${result ? ` · ${result.elapsed_ms} ms` : ""}`
    : null;

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        crumbs={["Home", "Investigate", "Search"]}
        title="Search"
        meta={meta}
        commands={
          <>
            <Command
              label={pending ? "Running…" : "Run query"}
              primary
              onClick={runCurrent}
              disabled={pending || (tab === "ask" && !askAnswer)}
            />
            {canSave ? (
              <Command
                label="Save"
                onClick={() => {
                  setSavedId(null);
                  setScheduleAfterSave(false);
                  setSaving(true);
                }}
                disabled={saving || !sqlToSave.trim()}
              />
            ) : null}
            {canSave ? (
              <Command
                label="Schedule"
                title="Save this search, then put it on a schedule"
                onClick={() => {
                  if (savedId) {
                    seedSchedule({ kind: "search", targetId: savedId });
                    navigate("schedules");
                    return;
                  }
                  setScheduleAfterSave(true);
                  setSaving(true);
                }}
                disabled={saving || !sqlToSave.trim()}
              />
            ) : null}
            <Command
              label={exporter.isPending ? "Exporting…" : "Export CSV"}
              onClick={() => lastRequest.current && exporter.mutate(lastRequest.current)}
              disabled={!result || result.rows.length === 0 || exporter.isPending}
            />
          </>
        }
      />

      <div className="flex flex-col gap-2.5 px-5 py-3">
        <FilterBar range={range} onRange={setRange} sources={sources} onSources={setSources} />
        <SearchTabs tab={tab} onTab={setTab} canAsk={canAsk} />
        {/* Panels stay mounted so a question and its turns survive a look at another tab. */}
        <div hidden={tab !== "simple"}>
          <SimplePanel
            text={text}
            onText={setText}
            onRun={() => simple.mutate({ text })}
            compiled={compiled}
            emptyColumns={emptyColumns}
            onEditAsSql={() => {
              if (!compiled) return;
              setSql(inlineParams(compiled));
              setTab("sql");
            }}
            pending={pending}
          />
        </div>
        {canAsk ? (
          <div hidden={tab !== "ask"}>
            <AskPanel
              start={rangeStart(range)}
              sources={sources}
              isAdmin={isAdmin}
              onRun={runAsk}
              onAnswer={setAskAnswer}
              pending={pending}
            />
          </div>
        ) : null}
        {/* hidden goes on a plain wrapper: a display class such as flex would override it. */}
        <div hidden={tab !== "sql"}>
          <div
            id="search-panel-sql"
            role="tabpanel"
            aria-labelledby="search-tab-sql"
            className="flex flex-col gap-2.5"
          >
            <SqlEditor
              label="SQL query"
              value={sql}
              onChange={setSql}
              onRun={runSql}
              columns={columnNames}
            />
            <div className="flex flex-wrap items-center gap-4 text-sm text-text-muted">
              <button
                type="button"
                onClick={() => runSql(sql)}
                disabled={pending}
                className="h-8 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
              >
                {pending ? "Running…" : "Run"}
              </button>
              <span>Ctrl+Enter to run · Ctrl+Space for columns</span>
              <span>Read-only · SELECT only · guarded by the server</span>
            </div>
          </div>
        </div>
        {saving ? (
          <SaveSearchForm
            sql={sqlToSave}
            askQuestion={tab === "ask" ? askAnswer?.question : undefined}
            simpleText={
              tab === "simple" && compiled?.text.trim() ? compiled.text.trim() : undefined
            }
            onCancel={() => {
              setSaving(false);
              setScheduleAfterSave(false);
            }}
            onDone={(id) => {
              setSaving(false);
              setSavedId(id);
              if (scheduleAfterSave) {
                setScheduleAfterSave(false);
                seedSchedule({ kind: "search", targetId: id });
                navigate("schedules");
              }
            }}
          />
        ) : null}
        {savedId ? (
          <p role="status" className="text-sm text-text-secondary">
            Saved as <span className="font-mono text-text">{savedId}</span>. Run it from Saved
            searches or with <span className="font-mono">remnant search {savedId}</span>.
          </p>
        ) : null}
        {simple.isError ? (
          <div role="alert" className={ALERT}>
            {simple.error instanceof Error ? simple.error.message : "The search could not be read"}
          </div>
        ) : null}
        {exporter.isError ? (
          <div role="alert" className={ALERT}>
            {exporter.error instanceof Error ? exporter.error.message : "Export failed"}
          </div>
        ) : null}
        {run.isError ? (
          <div role="alert" className={ALERT}>
            {run.error instanceof Error ? run.error.message : "Query failed"}
          </div>
        ) : null}
      </div>

      <FieldActionsContext.Provider value={actions}>
        <ResultsCard
          result={result}
          pending={pending}
          runKey={(result?.executed_sql ?? "") + (lastRun?.getTime() ?? 0)}
          canExplain={canSave}
        />
      </FieldActionsContext.Provider>
    </div>
  );
}
