import { useMutation, useQuery } from "@tanstack/react-query";
import { When } from "@/components/When";
import { withChunkReload } from "@/lib/chunkReload";
import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import {
  api,
  type CompiledSearch,
  type FacetRequest,
  type QueryRequest,
  type QueryResult,
  type SavedSearch,
} from "@/lib/api";
import {
  DEFAULT_SQL,
  logsRange,
  rangeStart,
  sameButValues,
  sqlPlaceholders,
  type LogsRange,
} from "@/lib/search";
import { localInput, windowOf } from "@/lib/timeWindow";
import { openSavedSearch } from "@/lib/savedSeed";
import { navigate, pathFor } from "@/lib/route";
import { seedSchedule } from "@/lib/scheduleSeed";
import { RUN_SEARCH_EVENT, takeSearchSeed } from "@/lib/searchSeed";
import {
  SEARCH_PATH,
  goToSearch,
  readSearchUrl,
  recordSearch,
  type SearchUrlState,
} from "@/lib/searchUrl";
import {
  addTerm,
  filterTerm,
  inlineParams,
  storeTab,
  storedTab,
  type SearchTab,
} from "@/lib/simpleSearch";
import { AddToDashboardPanel } from "@/features/dashboard/AddToDashboard";
import { FacetSidebar } from "./FacetSidebar";
import { FieldActionsContext, type FieldActions } from "./fieldActions";
import { FilterBar } from "./FilterBar";
import { OpenSearchPanel } from "./OpenSearchPanel";
import { LivePanel } from "./LivePanel";
import { downloadCsv, ResultsCard } from "./ResultsCard";
import { SaveSearchForm } from "./SaveSearchForm";
import { SearchTabs } from "./SearchTabs";
import { SimplePanel } from "./SimplePanel";

const FILL_KEY = "app.live.fill"; // Live starts with the last 5 minutes (per browser)

// CodeMirror is most of the bundle; it loads as its own chunk after the page shows.
const SqlEditor = lazy(
  withChunkReload(() => import("./SqlEditor").then((m) => ({ default: m.SqlEditor }))),
);

interface SearchPageProps {
  /** Admins and analysts author saved searches; auditors are read-only (SPEC 3.6). */
  canSave: boolean;
}

// `text` marks a run that came from a Simple search: sent with the query (the server reads
// it newest day first) and used for the facet counts.
type Run = Pick<QueryRequest, "sql" | "params"> & { text?: string };
// Field actions apply to text, number, and true/false columns; never to the raw line.
const ACTION_TYPES = new Set(["string", "int", "bool"]);
const NO_ACTIONS = new Set(["raw"]);

const ALERT = "rounded border border-danger px-3 py-2 text-sm text-danger";

/** Custom on Logs: local date-times, and the exact window a drill-through came with. */
interface LogsCustom {
  from: string;
  to: string;
  exact?: { from: string; to: string };
}

/**
 * Logs (ADR-0008, ADR-0009, D206): Filters (the Simple syntax) or SQL writes the query; one
 * results table shows it. Everything runs through /api/query, its guard, and its audit.
 * Ask AI is its own page and hands its SQL here with Open in Logs.
 */
export function SearchPage({ canSave }: SearchPageProps) {
  // A handoff from another page (rule matches) opens on the SQL tab over all time.
  const [seed] = useState(takeSearchSeed);
  const sqlSeed = seed?.sql !== undefined;
  // Back, Forward, a bookmark, or a shared link (D90): the address says what to show.
  const [urlState] = useState(() => (seed ? null : readSearchUrl()));
  // Two modes (D206): Filters and SQL.
  const [tab, setChosen] = useState<SearchTab>(() =>
    sqlSeed ? "sql" : urlState ? urlState.tab : storedTab(),
  );
  // The SQL editor (CodeMirror, the largest chunk) loads the first time the SQL tab is
  // opened, then stays mounted so its text and history survive tab changes.
  const [sqlSeen, setSqlSeen] = useState(tab === "sql");
  if (tab === "sql" && !sqlSeen) setSqlSeen(true);
  // Only a click on a tab is remembered as this browser's mode. Opening a saved or library
  // search, or refining one into SQL, switches the tab for this visit only, so Logs keeps
  // opening on Filters unless the person chose SQL.
  const setTab = setChosen;
  const chooseTab = (t: SearchTab) => {
    setChosen(t);
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
  // The time filter (ADR-0052 section 3.7): one of the four fixed windows, or Custom. SQL
  // handed over by another page opens on everything kept (Custom with no dates) unless it
  // names a range: the query often carries its own time.
  const asked = logsRange(
    seed?.range ?? (seed || !urlState ? (sqlSeed ? "all" : "24h") : urlState.range),
  );
  const [range, setRange] = useState<LogsRange>(asked.range);
  // Custom: a start and an end as local date-times. A window another page handed over (a
  // drill-through) keeps its exact bounds until the person edits a side, so the rows are
  // the ones the number counted.
  const [custom, setCustom] = useState<LogsCustom | null>(
    seed?.window
      ? {
          from: localInput(seed.window.from),
          to: localInput(seed.window.to),
          exact: seed.window,
        }
      : seed?.custom
        ? seed.custom
        : asked.open
          ? { from: "", to: "" }
          : (urlState?.custom ?? null),
  );
  const span = custom ? windowOf({ preset: "custom", from: custom.from, to: custom.to }) : null;
  const bounds = custom?.exact
    ? { start: custom.exact.from, end: custom.exact.to }
    : span
      ? { start: span.from?.toISOString(), end: span.to?.toISOString() }
      : { start: rangeStart(range) };
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
  const customNow = useRef(custom);
  customNow.current = custom;
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
        text: req.text,
        ...bounds,
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
      const scope = { start: body.start, end: body.end, sources: body.sources };
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
  // A field click in SQL mode: the server adds the filter to the SQL on screen
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
    queryKey: ["field-coverage", filtered, range, custom, sources, lastRun?.getTime()],
    enabled: tab === "simple" && filtered.length > 0 && run.isSuccess,
    queryFn: () =>
      api.query({
        sql: `SELECT ${filtered.map((c) => `count("${c}") AS "${c}"`).join(", ")} FROM events`,
        ...bounds,
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
  // Live (ADR-0036): the SQL it follows; null is off. A shared link never starts it.
  const [liveSql, setLiveSql] = useState<string | null>(null);
  const [liveKey, setLiveKey] = useState(0);
  const [liveFill, setLiveFill] = useState(() => {
    try {
      return localStorage.getItem(FILL_KEY) === "1";
    } catch {
      return false;
    }
  });
  // A query opened from Logs > Library, named above the editor while its SQL is unchanged.
  const [libraryQuery] = useState(() =>
    seed?.library && seed.sql !== undefined ? { ...seed.library, sql: seed.sql } : null,
  );
  // No rows from the library query as loaded, or with only its values changed (an
  // address, D274): its own words in place of the generic advice.
  const ran = run.variables;
  const libraryEmpty =
    libraryQuery?.empty &&
    result?.rows.length === 0 &&
    ran?.text === undefined &&
    ran?.sql !== undefined &&
    (libraryQuery.packSql
      ? sameButValues(ran.sql, libraryQuery.packSql)
      : ran.sql === libraryQuery.sql)
      ? libraryQuery.empty
      : undefined;
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
    const picked = customNow.current;
    const custom = picked ?? undefined;
    const simpleOrigin = open?.origin?.simple_text;
    let state: SearchUrlState;
    if (open && (vars.text !== undefined ? vars.text === simpleOrigin : vars.sql === open.sql)) {
      const params = Object.fromEntries(
        Object.entries(vars.params ?? {}).map(([k, v]) => [k, String(v)]),
      );
      state = {
        tab: vars.text !== undefined ? "simple" : "sql",
        saved: open.id,
        params,
        range,
        custom,
      };
    } else if (vars.text !== undefined) {
      state = { tab: "simple", q: vars.text, range, custom };
    } else {
      state = { tab: "sql", q: vars.sql, range, custom };
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
    goToSearch(SEARCH_PATH);
  };
  const edited = opened
    ? opened.origin?.simple_text !== undefined
      ? text !== opened.origin.simple_text
      : sql !== opened.sql
    : false;
  const runCurrent = () => {
    if (tab === "simple") simple.mutate({ text });
    else runSql(sql);
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
    // A library query only loads (ADR-0033 row 4): the person runs it with Run.
    if (seed?.library) return;
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
  const sqlToSave = tab === "simple" ? (compiled ? inlineParams(compiled) : DEFAULT_SQL) : sql;
  // SQL handed over from Ask AI and not changed since: Save keeps its question (D206).
  const askQuestion =
    tab === "sql" && seed?.askQuestion && sql === seed.sql ? seed.askQuestion : undefined;

  // The viewer's clock, UTC on hover, as times read everywhere else (owner, 2026-11-08).
  const meta = lastRun ? (
    <span>
      Last run <When iso={lastRun.toISOString()} />
      {result ? ` · ${result.elapsed_ms} ms` : ""}
    </span>
  ) : null;

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      {/* Run is the page's one filled button and sits beside what it runs, in the Filters
          and SQL panels below (DESIGN.md 6.1), so the header has no primary. */}
      <PageHeader
        title="Logs"
        // Export CSV is under More, which closes on a choice: say here that it is running.
        count={exporter.isPending ? <span role="status">Exporting…</span> : meta}
        secondary={[
          ...(canSave
            ? [
                {
                  label: "Save",
                  onClick: () => {
                    setSaved(null);
                    setScheduleAfterSave(false);
                    setSaving(true);
                  },
                  disabled: saving || !sqlToSave.trim(),
                },
              ]
            : []),
          {
            label: "Open",
            title: "Open a saved search here",
            onClick: () => setOpening((v) => !v),
          },
        ]}
        menu={[
          {
            label: "New search",
            title: "Start over: close any open search and clear both editors",
            onClick: () => (unsaved ? setConfirmNew(true) : startNew()),
          },
          {
            label: "Library",
            title: "Open the Library tab: shipped, tested queries",
            onClick: () => navigate("library"),
          },
          ...(canSave
            ? [
                {
                  label: "Schedule",
                  title: "Save this search, then put it on a schedule",
                  onClick: () => {
                    if (savedId) {
                      seedSchedule({ kind: "search", targetId: savedId });
                      navigate("schedules");
                      return;
                    }
                    setScheduleAfterSave(true);
                    setSaving(true);
                  },
                  disabled: saving || !sqlToSave.trim(),
                },
                {
                  label: "Add to dashboard",
                  title: "Put this search on the Dashboard: hourly, last 24 hours",
                  onClick: () => {
                    // The search as shown: the one just saved, or the open one if unchanged.
                    const current = saved ?? (opened && opened.sql === sql ? opened : null);
                    if (current && tab === "sql") {
                      setDashboardFor(current);
                      return;
                    }
                    setScheduleAfterSave(false);
                    setDashboardAfterSave(true);
                    setSaving(true);
                  },
                  disabled: saving || !sqlToSave.trim(),
                },
              ]
            : []),
          {
            label: exporter.isPending ? "Exporting…" : "Export CSV",
            onClick: () => {
              if (lastRequest.current) exporter.mutate(lastRequest.current);
            },
            disabled: !result || result.rows.length === 0 || exporter.isPending,
          },
        ]}
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
        <FilterBar
          range={range}
          custom={custom}
          onRange={(r) => {
            setCustom(null);
            setRange(r);
          }}
          onCustom={(from, to) => setCustom({ from, to })}
          sources={sources}
          onSources={setSources}
        />
        <SearchTabs active={tab} onSelect={chooseTab} />
        {/* Panels stay mounted so the text in each survives a look at the other mode. */}
        <div hidden={tab !== "simple"}>
          <div id="search-panel-simple" role="tabpanel" aria-labelledby="search-tab-simple">
            <SimplePanel
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
        </div>
        {/* hidden goes on a plain wrapper: a display class such as flex would override it. */}
        <div hidden={tab !== "sql"}>
          <div
            id="search-panel-sql"
            role="tabpanel"
            aria-labelledby="search-tab-sql"
            className="flex flex-col gap-2.5"
          >
            {seed?.origin && sql === seed.sql ? (
              <p className="text-sm text-text-secondary">{seed.origin}</p>
            ) : null}
            {libraryQuery && sql === libraryQuery.sql ? (
              <div
                role="note"
                aria-label="From the query library"
                className="flex flex-col gap-0.5 rounded border border-border bg-surface px-3 py-2 text-sm"
              >
                <span>
                  <span className="font-semibold">{libraryQuery.name}</span>
                  <span className="text-text-muted">
                    {" "}
                    from the {libraryQuery.packName} library, unsaved
                  </span>
                </span>
                <span>{libraryQuery.why}</span>
                <span className="text-text-muted">Normal: {libraryQuery.normal}</span>
              </div>
            ) : null}
            {sqlSeen ? (
              <Suspense fallback={<div className="h-40 rounded border border-border bg-inset" />}>
                <SqlEditor
                  label="SQL query"
                  value={sql}
                  onChange={setSql}
                  onRun={runSql}
                  columns={columnNames}
                />
              </Suspense>
            ) : null}
            {sqlPlaceholders(sql).length ? (
              <fieldset className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
                <legend className="sr-only">Parameters</legend>
                {sqlPlaceholders(sql).map((n) => (
                  <label key={n} className="flex items-center gap-2">
                    <span className="font-mono">{n}</span>
                    <input
                      value={paramValues[n] ?? ""}
                      onChange={(e) => setParamValues({ ...paramValues, [n]: e.target.value })}
                      className="h-8 w-40 rounded border border-border-control bg-inset px-2 font-mono text-sm"
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
              <label className="flex items-center gap-1.5 text-text">
                <input
                  type="checkbox"
                  role="switch"
                  aria-checked={liveSql !== null}
                  checked={liveSql !== null}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setLiveKey((k) => k + 1);
                      setLiveSql(sql);
                    } else setLiveSql(null);
                  }}
                />
                Live
              </label>
              <label className="flex items-center gap-1.5 text-text-secondary">
                <input
                  type="checkbox"
                  checked={liveFill}
                  onChange={(e) => {
                    setLiveFill(e.target.checked);
                    try {
                      localStorage.setItem(FILL_KEY, e.target.checked ? "1" : "0");
                    } catch {
                      // storage blocked: the choice lasts for this page only
                    }
                  }}
                />
                Start with the last 5 min
              </label>
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
            askQuestion={askQuestion}
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
              href={pathFor("saved")}
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
        {liveSql !== null ? (
          <LivePanel
            key={liveKey}
            sql={liveSql}
            sources={sources}
            fillMinutes={liveFill ? 5 : 0}
            onClose={() => setLiveSql(null)}
          />
        ) : null}
        <div className={liveSql !== null ? "hidden" : "contents"}>
          <FacetSidebar
            request={facetRequest}
            total={result ? { count: result.row_count, more: result.truncated } : null}
            onTerm={
              // The results on screen came from a Filters search: refine that search, even
              // when SQL has been opened since (the results are still its).
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
              // A library query only loads (ADR-0033 row 4): say what shows the rows.
              idle={libraryQuery ? "Press Run to see the rows." : undefined}
              emptyDetail={libraryEmpty}
            />
          </FieldActionsContext.Provider>
        </div>
      </div>
    </div>
  );
}
