import { useMutation, useQuery } from "@tanstack/react-query";
import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { Command, PageHeader } from "@/components/shell/PageHeader";
import {
  api,
  type CompiledSearch,
  type FacetRequest,
  type QueryRequest,
  type QueryResult,
  type SavedSearch,
} from "@/lib/api";
import { DEFAULT_SQL, rangeStart, sqlPlaceholders, type TimeRangeId } from "@/lib/search";
import { openSavedSearch } from "@/lib/savedSeed";
import { navigate } from "@/lib/route";
import { seedSchedule } from "@/lib/scheduleSeed";
import { RUN_SEARCH_EVENT, takeSearchSeed } from "@/lib/searchSeed";
import { goToSearch, readSearchUrl, recordSearch, type SearchUrlState } from "@/lib/searchUrl";
import {
  addTerm,
  filterTerm,
  inlineParams,
  storeTab,
  storedTab,
  type SearchTab,
} from "@/lib/simpleSearch";
import { AddToDashboardPanel } from "@/features/dashboard/AddToDashboard";
import { AiToggle } from "./AiToggle";
import { AskPanel } from "./AskPanel";
import { FacetSidebar } from "./FacetSidebar";
import { FieldActionsContext, type FieldActions } from "./fieldActions";
import { FilterBar } from "./FilterBar";
import { OpenSearchPanel } from "./OpenSearchPanel";
import { downloadCsv, ResultsCard } from "./ResultsCard";
import { SaveSearchForm } from "./SaveSearchForm";
import { SearchTabs, type SearchArea } from "./SearchTabs";
import { SimplePanel } from "./SimplePanel";

// CodeMirror is most of the bundle; it loads as its own chunk after the page shows.
const SqlEditor = lazy(() => import("./SqlEditor").then((m) => ({ default: m.SqlEditor })));

interface SearchPageProps {
  /** Admins and analysts author saved searches; auditors are read-only (SPEC 3.6). */
  canSave: boolean;
  /** Admins and analysts may ask a model; auditors have no Ask. */
  canAsk?: boolean;
  isAdmin?: boolean;
  /** /ask opens the Ask tab (ADR-0008). */
  initialTab?: SearchTab;
}

// `text` marks a run that came from a Simple search (for the facet counts); not sent.
type Run = Pick<QueryRequest, "sql" | "params"> & { text?: string };
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
  // Back, Forward, a bookmark, or a shared link (D90): the address says what to show.
  const [urlState] = useState(() => (seed ? null : readSearchUrl()));
  // Two tabs (ADR-0016 row 1): Search, with the AI switch choosing Simple or Ask, and SQL.
  const [initial] = useState<SearchTab>(() =>
    sqlSeed ? "sql" : urlState ? urlState.tab : (initialTab ?? storedTab()),
  );
  const [area, setArea] = useState<SearchArea>(initial === "sql" ? "sql" : "search");
  const [mode, setMode] = useState<"simple" | "ask">(initial === "ask" ? "ask" : "simple");
  const searchMode = mode === "ask" && !canAsk ? "simple" : mode;
  const tab: SearchTab = area === "sql" ? "sql" : searchMode;
  const setTab = (t: SearchTab) => {
    if (t === "sql") setArea("sql");
    else {
      setArea("search");
      setMode(t);
    }
    storeTab(t);
  };
  const [facetRequest, setFacetRequest] = useState<FacetRequest | null>(null);
  const presets = useQuery({
    queryKey: ["search-presets"],
    queryFn: api.searchPresets,
    staleTime: Infinity,
  });
  const [text, setText] = useState(urlState?.tab === "simple" ? (urlState.q ?? "") : "");
  // The last compiled Simple search and the text it came from (saved as the origin).
  const [compiled, setCompiled] = useState<(CompiledSearch & { text: string }) | null>(null);
  const [sql, setSql] = useState(
    seed?.sql ?? (urlState?.tab === "sql" && urlState.q ? urlState.q : DEFAULT_SQL),
  );
  const [askAnswer, setAskAnswer] = useState<{ sql: string; question: string } | null>(null);
  const [range, setRange] = useState<TimeRangeId>(
    seed?.range ?? urlState?.range ?? (sqlSeed ? "all" : "24h"),
  );
  const [sources, setSources] = useState<string[]>(seed?.sources ?? []);
  const [lastRun, setLastRun] = useState<Date | null>(null);
  const [saving, setSaving] = useState(false);
  // Schedule saves first (a schedule runs a saved search), then opens the schedule form.
  const [scheduleAfterSave, setScheduleAfterSave] = useState(false);
  // Add to dashboard (D89): a saved search goes on the Dashboard with panel defaults.
  const [dashboardAfterSave, setDashboardAfterSave] = useState(false);
  const [dashboardFor, setDashboardFor] = useState<SavedSearch | null>(null);
  const [saved, setSaved] = useState<SavedSearch | null>(null);
  const savedId = saved?.id ?? null;
  // Open (install finding 13): the saved search loaded here, and values for its
  // {{name}} placeholders. {{start}} and {{end}} come from the time range.
  const [opening, setOpening] = useState(false);
  const [opened, setOpened] = useState<SavedSearch | null>(null);
  // Mutation callbacks keep the render they were started from; these are always current.
  const openedNow = useRef<SavedSearch | null>(null);
  openedNow.current = opened;
  const rangeNow = useRef(range);
  rangeNow.current = range;
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
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
        sql: req.sql,
        params: req.params,
        start: rangeStart(range),
        sources: sources.length ? sources : undefined,
      };
      lastRequest.current = body;
      return api.query(body);
    },
    onSuccess: (data, vars) => {
      setLastRun(new Date());
      remember(vars);
      const body = lastRequest.current;
      if (!body) return;
      const scope = { start: body.start, sources: body.sources };
      setFacetRequest(
        vars.text !== undefined
          ? { text: vars.text, ...scope }
          : { sql: body.sql, params: body.params, columns: data.columns, ...scope },
      );
    },
  });
  const simple = useMutation({
    mutationFn: (v: { text: string; top?: string }) => api.compileSearch(v.text, v.top),
    onSuccess: (c, v) => {
      if (!v.top) setCompiled({ ...c, text: v.text });
      run.mutate({ sql: c.sql, params: c.params, text: v.top ? undefined : v.text });
    },
  });
  const exporter = useMutation({ mutationFn: downloadCsv });
  // A field click in SQL or Ask mode: the server adds the filter to the SQL on screen
  // (as a syntax tree, value quoted), the editor shows it, and it runs like any query.
  const refine = useMutation({
    mutationFn: (v: { field: string; value: string | null; exclude: boolean }) => {
      const body = lastRequest.current;
      if (!body) throw new Error("Run a search first");
      return api.refineQuery({ sql: body.sql, ...v }).then((r) => ({ ...r, params: body.params }));
    },
    onSuccess: (r) => {
      setSql(r.sql);
      setTab("sql");
      run.mutate({ sql: r.sql, params: r.params });
    },
  });
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

  const typed = (name: string, value: string, defs: SavedSearch["params"]) => {
    const type = defs.find((d) => d.name === name)?.type;
    if (type === "int" || type === "float") return Number(value);
    if (type === "bool") return value === "true";
    return value;
  };
  const runSql = (value: string, values = paramValues, defs = opened?.params ?? []) => {
    const names = sqlPlaceholders(value);
    const params = Object.fromEntries(
      names
        .filter((n) => values[n] !== undefined && values[n] !== "")
        .map((n) => [n, typed(n, values[n] ?? "", defs)]),
    );
    run.mutate({ sql: value, params: names.length ? params : undefined });
  };
  const openSearch = (s: SavedSearch, given: Record<string, string> = {}) => {
    setOpening(false);
    setOpened(s);
    openedNow.current = s;
    setSaved(null);
    const values = Object.fromEntries(
      s.params.map((p) => [
        p.name,
        given[p.name] ?? (p.default === undefined || p.default === null ? "" : String(p.default)),
      ]),
    );
    setParamValues(values);
    const simpleText = s.origin?.simple_text;
    if (simpleText !== undefined) {
      setText(simpleText);
      setTab("simple");
      simple.mutate({ text: simpleText });
      return;
    }
    setSql(s.sql);
    setTab("sql");
    // Run now unless a parameter still needs a value.
    if (sqlPlaceholders(s.sql).every((n) => values[n])) runSql(s.sql, values, s.params);
  };
  // What ran last, for Back and Forward (D90) and for "unsaved edits" before New search.
  const recorded = useRef(false);
  const lastRan = useRef<{ sql: string | null; text: string | null }>({ sql: null, text: null });
  const remember = (vars: Run) => {
    if (vars.text !== undefined) lastRan.current.text = vars.text;
    else lastRan.current.sql = vars.sql;
    const open = openedNow.current;
    const range = rangeNow.current;
    const simpleOrigin = open?.origin?.simple_text;
    let state: SearchUrlState;
    if (open && (vars.text !== undefined ? vars.text === simpleOrigin : vars.sql === open.sql)) {
      const params = Object.fromEntries(
        Object.entries(vars.params ?? {}).map(([k, v]) => [k, String(v)]),
      );
      state = { tab: vars.text !== undefined ? "simple" : "sql", saved: open.id, params, range };
    } else if (vars.text !== undefined) {
      state = { tab: "simple", q: vars.text, range };
    } else {
      state = { tab: "sql", q: vars.sql, range };
    }
    recordSearch(state, !recorded.current);
    recorded.current = true;
  };
  const [confirmNew, setConfirmNew] = useState(false);
  const unsaved =
    (sql !== DEFAULT_SQL && sql !== lastRan.current.sql && sql !== opened?.sql) ||
    (text.trim() !== "" && text !== lastRan.current.text);
  const startNew = () => {
    storeTab("simple");
    goToSearch("/search");
  };
  const edited = opened
    ? opened.origin?.simple_text !== undefined
      ? text !== opened.origin.simple_text
      : sql !== opened.sql
    : false;
  const runAsk = (value: string) => {
    setSql(value); // the editor always holds what produced the results
    runSql(value);
  };
  const runCurrent = () => {
    if (tab === "simple") simple.mutate({ text });
    else if (tab === "sql") runSql(sql);
    else if (askAnswer) runAsk(askAnswer.sql);
  };

  // A saved search to open on arrival: Saved searches > Edit (F37), or an address that
  // names one (D90). Edit also opens the Save form, so Save changes updates it.
  const toOpen = seed?.savedId ?? urlState?.saved;
  const editing = useQuery({
    queryKey: ["searches"],
    queryFn: api.searches,
    enabled: Boolean(toOpen),
  });
  const editTaken = useRef(false);
  useEffect(() => {
    if (editTaken.current || !toOpen || !editing.data) return;
    editTaken.current = true;
    const found = editing.data.find((s) => s.id === toOpen);
    if (!found) {
      runSql(sql); // gone, or not shared with this reader: show recent events instead
      return;
    }
    openSearch(found, urlState?.params);
    if (seed?.savedId) setSaving(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing.data, editing.isError]);

  // Run once on open so the page shows recent events immediately.
  useEffect(() => {
    if (toOpen) return; // the saved search runs once it is loaded
    if (sqlSeed || tab === "sql") runSql(sql);
    else simple.mutate({ text });
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
            <Command
              label="New search"
              title="Start over: close any open search and clear both editors"
              onClick={() => (unsaved ? setConfirmNew(true) : startNew())}
            />
            <Command
              label="Open"
              title="Open a saved search here"
              onClick={() => setOpening((v) => !v)}
            />
            {canSave ? (
              <Command
                label="Save"
                onClick={() => {
                  setSaved(null);
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
            {canSave ? (
              <Command
                label="Add to dashboard"
                title="Put this search on the Dashboard: hourly, last 24 hours"
                onClick={() => {
                  // The search as shown: the one just saved, or the open one if unchanged.
                  const current = saved ?? (opened && opened.sql === sql ? opened : null);
                  if (current && tab === "sql") {
                    setDashboardFor(current);
                    return;
                  }
                  setScheduleAfterSave(false);
                  setDashboardAfterSave(true);
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
        {opening ? <OpenSearchPanel onOpen={openSearch} onClose={() => setOpening(false)} /> : null}
        {confirmNew ? (
          <div
            role="alertdialog"
            aria-label="Discard unsaved edits"
            className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded border border-warn bg-surface px-3 py-2 text-sm"
          >
            <span>Your edits are not saved or run. Start a new search anyway?</span>
            <button
              type="button"
              onClick={startNew}
              className="h-7 rounded border border-border px-2.5 hover:bg-surface-head"
            >
              Discard and start new
            </button>
            <button
              type="button"
              onClick={() => setConfirmNew(false)}
              className="h-7 rounded px-2.5 text-accent-text hover:bg-surface-head"
            >
              Keep editing
            </button>
          </div>
        ) : null}
        {!opened ? (
          <p className="text-sm text-text-secondary" data-testid="search-state">
            Unsaved search
          </p>
        ) : null}
        {opened ? (
          <p className="text-sm text-text-secondary" data-testid="search-state">
            Open: <span className="text-text">{opened.name}</span>{" "}
            <span className="font-mono text-text-muted">{opened.id}</span>
            {edited ? <span className="text-warn"> · edited, not saved</span> : null}. Save keeps
            changes in it.{" "}
            <button
              type="button"
              onClick={() => setOpened(null)}
              className="text-accent-text hover:underline"
            >
              Close it
            </button>
          </p>
        ) : null}
        <FilterBar range={range} onRange={setRange} sources={sources} onSources={setSources} />
        <SearchTabs active={area} onSelect={(a) => setTab(a === "sql" ? "sql" : searchMode)} />
        {/* Panels stay mounted so a question and its turns survive a look at another tab. */}
        <div hidden={area !== "search"}>
          <div id="search-panel-search" role="tabpanel" aria-labelledby="search-tab-search">
            <div hidden={tab !== "simple"}>
              <SimplePanel
                toggle={canAsk ? <AiToggle on={false} onChange={() => setTab("ask")} /> : undefined}
                presets={presets.data ?? []}
                onPreset={(value) => {
                  setText(value);
                  simple.mutate({ text: value });
                }}
                text={text}
                onText={setText}
                onRun={() => simple.mutate({ text })}
                compiled={compiled}
                emptyColumns={emptyColumns}
                onMoveToSql={(q) => {
                  setSql(q);
                  setText("");
                  setTab("sql");
                }}
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
                  toggle={<AiToggle on onChange={() => setTab("simple")} />}
                />
              </div>
            ) : null}
          </div>
        </div>
        {/* hidden goes on a plain wrapper: a display class such as flex would override it. */}
        <div hidden={tab !== "sql"}>
          <div
            id="search-panel-sql"
            role="tabpanel"
            aria-labelledby="search-tab-sql"
            className="flex flex-col gap-2.5"
          >
            <Suspense fallback={<div className="h-40 rounded border border-border bg-inset" />}>
              <SqlEditor
                label="SQL query"
                value={sql}
                onChange={setSql}
                onRun={runSql}
                columns={columnNames}
              />
            </Suspense>
            {sqlPlaceholders(sql).length ? (
              <fieldset className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
                <legend className="sr-only">Parameters</legend>
                {sqlPlaceholders(sql).map((n) => (
                  <label key={n} className="flex items-center gap-2">
                    <span className="font-mono">{n}</span>
                    <input
                      value={paramValues[n] ?? ""}
                      onChange={(e) => setParamValues({ ...paramValues, [n]: e.target.value })}
                      className="h-8 w-40 rounded border border-border-strong bg-inset px-2 font-mono text-sm"
                    />
                  </label>
                ))}
              </fieldset>
            ) : null}
            {/\{\{\s*(start|end)\s*\}\}/.test(sql) ? (
              <p className="text-sm text-text-muted">
                <span className="font-mono">{"{{start}}"}</span> and{" "}
                <span className="font-mono">{"{{end}}"}</span> come from the time range above.
              </p>
            ) : null}
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
            key={opened?.id ?? "new"}
            existing={opened}
            sql={sqlToSave}
            askQuestion={tab === "ask" ? askAnswer?.question : undefined}
            simpleText={
              tab === "simple" && compiled?.text.trim() ? compiled.text.trim() : undefined
            }
            onCancel={() => {
              setSaving(false);
              setScheduleAfterSave(false);
              setDashboardAfterSave(false);
            }}
            onDone={(s) => {
              setSaving(false);
              setSaved(s);
              setOpened(s);
              if (dashboardAfterSave) {
                setDashboardAfterSave(false);
                setDashboardFor(s);
              }
              if (scheduleAfterSave) {
                setScheduleAfterSave(false);
                seedSchedule({ kind: "search", targetId: s.id });
                navigate("schedules");
              }
            }}
          />
        ) : null}
        {dashboardFor ? (
          <AddToDashboardPanel
            key={dashboardFor.id}
            search={dashboardFor}
            result={result ?? null}
            onClose={() => setDashboardFor(null)}
          />
        ) : null}
        {saved ? (
          <p
            role="status"
            className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded border border-ok bg-surface px-3 py-2 text-sm"
          >
            <span>
              Saved as <span className="font-semibold">{saved.name}</span>{" "}
              <span className="font-mono text-text-muted">{saved.id}</span>.
            </span>
            <a
              href="/saved"
              onClick={(e) => {
                e.preventDefault();
                openSavedSearch(saved.id);
                navigate("saved");
              }}
              className="text-accent-text hover:underline"
            >
              Open in Saved searches
            </a>
            <button
              type="button"
              onClick={() => {
                seedSchedule({ kind: "search", targetId: saved.id });
                navigate("schedules");
              }}
              className="text-accent-text hover:underline"
            >
              Schedule it
            </button>
            <span className="text-text-muted">
              CLI: <span className="font-mono">remnant search {saved.id}</span>
            </span>
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
        {refine.isError ? (
          <div role="alert" className={ALERT}>
            {refine.error instanceof Error ? refine.error.message : "Could not add the filter"}
          </div>
        ) : null}
        {run.isError ? (
          <div role="alert" className={ALERT}>
            {run.error instanceof Error ? run.error.message : "Query failed"}
          </div>
        ) : null}
      </div>

      <div className="mx-5 mb-5 flex flex-col gap-3 lg:flex-row">
        <FacetSidebar
          request={facetRequest}
          onTerm={
            // The results on screen came from a Simple search: refine that search, even
            // when the Ask or SQL tab has been opened since (the results are still its).
            facetRequest?.text !== undefined
              ? (term) => {
                  const next = addTerm(facetRequest.text ?? "", term);
                  setText(next);
                  setTab("simple");
                  simple.mutate({ text: next });
                }
              : null
          }
          onRefine={
            facetRequest?.sql !== undefined
              ? (field, value, exclude) => refine.mutate({ field, value, exclude })
              : null
          }
        />
        <FieldActionsContext.Provider value={actions}>
          <ResultsCard
            result={result}
            pending={pending}
            runKey={(result?.executed_sql ?? "") + (lastRun?.getTime() ?? 0)}
            canExplain={canSave}
          />
        </FieldActionsContext.Provider>
      </div>
    </div>
  );
}
