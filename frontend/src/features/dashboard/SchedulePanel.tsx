import { EntityLink } from "@/components/EntityLink";
import { kindForColumn, type EntityKind } from "@/lib/entity";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type KeyboardEvent } from "react";
import {
  ApiError,
  api,
  type Cell,
  type DashboardPanel,
  type HeadlineKind,
  type PanelSize,
  type Schedule,
} from "@/lib/api";
import { navigate } from "@/lib/route";
import { eventsSql, seedSearch } from "@/lib/searchSeed";
import { cronLabel, fillSql } from "@/features/schedules/schedule";
import { since, stamp } from "@/features/overview/time";
import { flagText, formatHeadline, headlineValue, hasTrend, panelLabel, trend } from "./headline";
import { barShape, cellText, COLUMNS_AT, type PanelView, type PanelWidth } from "./panelShape";
import { Sparkline } from "./Sparkline";

const TOP_ROWS = 5;
const TOP_BARS = 10;
const SIZES: [PanelSize, string][] = [
  ["tile", "Tile"],
  ["third", "1/3"],
  ["half", "1/2"],
  ["full", "Full"],
];
const HEADLINES: [HeadlineKind, string][] = [
  ["rows", "Row count"],
  ["sum", "Sum of"],
  ["distinct", "Count distinct"],
  ["first", "First row value of"],
];

interface SchedulePanelProps {
  schedule: Schedule;
  panel: DashboardPanel;
  dashboardId: string;
  /** The dashboard's owner or an admin, with Edit layout on: size, view, section, order. */
  editing: boolean;
  /** The schedule's owner or an admin: may set what the headline counts. */
  canManage: boolean;
  onMove?: (step: -1 | 1) => void;
  onRemove?: () => void;
  /** The dashboard's sections, for Move to section (the keyboard way to move a panel). */
  sections?: string[];
  onMoveTo?: (section: string) => void;
}

function open(sql: string) {
  seedSearch({ sql });
  navigate("search");
}

function onActivate(go: () => void) {
  return {
    role: "button" as const,
    tabIndex: 0,
    onClick: go,
    onKeyDown: (e: KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        go();
      }
    },
  };
}

/** One schedule on a dashboard (SPEC 5.5, ADR-0034): the headline number and what it
 * counts, the trend, the flag, and (except on a tile) the top rows as a table or bars. */
export function SchedulePanel({
  schedule: s,
  panel,
  dashboardId,
  editing,
  canManage,
  onMove,
  onRemove,
  sections = [],
  onMoveTo,
}: SchedulePanelProps) {
  const client = useQueryClient();
  const last = s.recent[0];
  const readable = Boolean(last && last.status === "ok" && !last.restricted);
  const tile = panel.size === "tile";
  const width: PanelWidth = panel.size === "tile" ? "third" : panel.size;
  const detail = useQuery({
    queryKey: ["schedule-run", s.schedule_id, last?.run_id],
    queryFn: () => api.scheduleRun(s.schedule_id, last?.run_id ?? ""),
    enabled: readable,
  });
  const searches = useQuery({
    queryKey: ["searches"],
    queryFn: api.searches,
    enabled: s.kind === "search",
  });
  const layout = useMutation({
    mutationFn: (body: { size?: PanelSize; view?: PanelView; section?: string }) =>
      api.setPanel(dashboardId, s.schedule_id, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["dashboards"] }),
  });
  const run = detail.data;
  const shape = run ? barShape(run.columns, run.sample.slice(0, TOP_BARS)) : null;
  const view: PanelView = shape && panel.view === "bars" ? "bars" : "table";

  let openSql: string | null = null;
  if (run && readable) {
    if (s.kind === "rule") {
      openSql = eventsSql(run.sample.map((r) => String(r[0])));
    } else {
      const search = (searches.data ?? []).find((x) => x.id === s.target_id);
      if (search && run.range_start && run.range_end) {
        const values: Record<string, Cell> = {};
        for (const p of search.params) if (p.default != null) values[p.name] = p.default;
        Object.assign(values, s.params);
        openSql = fillSql(search.sql, values, run.range_start, run.range_end);
      }
    }
  }
  // A rule's row opens that event; a search's row opens the full result it came from.
  const openRow = (r: Cell[]): string | null =>
    s.kind === "rule" && r[0] != null ? eventsSql([String(r[0])]) : openSql;

  const shown = run ? Math.min(run.columns.length, COLUMNS_AT[width]) : 0;
  const rows = (run?.sample ?? []).slice(0, TOP_ROWS);
  const value = last && readable ? headlineValue(s, last) : null;
  const columns = run?.columns ?? [];
  const label = panelLabel(s, columns);
  const now = new Date().toISOString();
  // A detection-style search with nothing to report: zero is the good news (ADR-0034 row 2).
  const goodZero = value === "0" && s.threshold_kind !== null && !last?.flagged;
  const flag = last && !last.restricted ? flagText(s, last, columns) : null;

  if (tile && !editing) {
    return (
      <TileCard
        schedule={s}
        value={value}
        label={label}
        flag={flag}
        goodZero={goodZero}
        openSql={openSql}
        now={now}
      />
    );
  }

  return (
    <section
      id={`panel-${s.schedule_id}`}
      aria-label={s.name}
      className="flex h-full min-w-0 flex-col gap-2 rounded-card border border-border bg-surface p-3 text-sm"
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold" title={s.name}>
            {s.name}
          </div>
          {tile ? null : (
            <div className="text-text-muted">
              {s.kind === "search" ? "Saved search" : "Rule"}, {cronLabel(s.cron)}
            </div>
          )}
        </div>
        {flag ? <FlagBadge /> : null}
      </div>
      {s.paused ? (
        <p className="text-warn">Paused: {s.paused_reason ?? "by a person"}</p>
      ) : !last ? (
        <p className="text-text-secondary">Not run yet</p>
      ) : last.restricted ? (
        <p className="text-text-secondary">
          Restricted: this run read sources you cannot read, so its results are hidden.
        </p>
      ) : last.status === "failed" ? (
        <p className="text-danger">Last run failed: {last.error}</p>
      ) : (
        <>
          <div className={tile ? "flex flex-col gap-1" : "flex items-end justify-between gap-3"}>
            <div className="min-w-0">
              {value === null ? (
                <div className="text-text-secondary">
                  No value: {s.headline_column ?? "the column"} was not in the last result
                </div>
              ) : (
                <button
                  type="button"
                  disabled={!openSql}
                  onClick={() => openSql && open(openSql)}
                  title={openSql ? "Open the rows behind this number" : undefined}
                  className={`block max-w-full truncate text-left text-kpi tabular-nums ${goodZero ? "text-ok" : "text-text"} ${openSql ? "hover:underline" : "cursor-default"}`}
                >
                  {formatHeadline(value)}
                </button>
              )}
              <div className="text-text-muted">
                {label},{" "}
                <time dateTime={last.started_at} title={`${stamp(last.started_at)} UTC`}>
                  {since(last.started_at, now)}
                </time>
              </div>
            </div>
            {hasTrend(s) ? (
              <Sparkline values={trend(s)} label={`Counts of the last ${s.recent.length} runs`} />
            ) : null}
          </div>
          {flag ? (
            <p className="text-warn">{flag}</p>
          ) : goodZero && tile ? (
            <p className="text-ok">Nothing flagged</p>
          ) : null}
          {last.definition_change ? (
            <p className="text-text-secondary">Changed: {last.definition_change}</p>
          ) : null}
          {last.parser_change ? (
            <p role="note" className="text-warn">
              {last.parser_change}
            </p>
          ) : null}
          {tile ? null : run && shape && view === "bars" ? (
            <Bars
              name={s.name}
              rows={run.sample.slice(0, TOP_BARS)}
              shape={shape}
              valueName={run.columns[shape.value] ?? "count"}
              labelName={run.columns[shape.label] ?? ""}
              onOpen={openSql ? () => open(openSql as string) : null}
            />
          ) : rows.length && run ? (
            <div className="rounded border border-border">
              <table aria-label={`Top rows of ${s.name}`} className="w-full table-fixed">
                <thead>
                  <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
                    {run.columns.slice(0, shown).map((c) => (
                      <th key={c} title={c} className="truncate px-2 py-1 font-semibold">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const target = openRow(r);
                    return (
                      <tr
                        key={i}
                        {...(target ? onActivate(() => open(target)) : {})}
                        aria-label={target ? `Open row ${i + 1} in Search` : undefined}
                        className={`border-b border-border last:border-0 ${target ? "cursor-pointer hover:bg-surface-head focus-visible:bg-surface-head" : ""}`}
                      >
                        {r.slice(0, shown).map((v, j) => (
                          <td
                            key={j}
                            title={v === null ? emptyNote(run.columns[j] ?? "") : cellText(v)}
                            className="truncate px-2 py-1 font-mono"
                          >
                            {kindForColumn(run.columns[j] ?? "") ? (
                              <EntityLink
                                kind={kindForColumn(run.columns[j] ?? "") as EntityKind}
                                value={v}
                                label={cellText(v)}
                              />
                            ) : (
                              cellText(v)
                            )}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      )}
      <div className="mt-auto flex flex-wrap items-center gap-2 pt-1">
        {openSql ? (
          <button
            type="button"
            className="h-7 rounded border border-border px-2 text-accent-text hover:bg-surface-head"
            onClick={() => open(openSql as string)}
          >
            {tile ? "View rows" : run && shown < run.columns.length ? "View all" : "Open in Search"}
          </button>
        ) : null}
      </div>
      {editing ? (
        <div className="flex flex-col gap-2 border-t border-border pt-2">
          <div className="flex flex-wrap items-center gap-2">
            <Segmented
              label={`Size of ${s.name}`}
              options={SIZES}
              value={panel.size}
              onChange={(v) => layout.mutate({ size: v as PanelSize })}
            />
            {shape && !tile ? (
              <Segmented
                label={`View of ${s.name}`}
                options={[
                  ["table", "Table"],
                  ["bars", "Bars"],
                ]}
                value={view}
                onChange={(v) => layout.mutate({ view: v as PanelView })}
              />
            ) : null}
          </div>
          <MoveTo
            name={s.name}
            value={panel.section}
            sections={sections}
            onMove={(section) => onMoveTo?.(section)}
          />
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => onMove?.(-1)}
              aria-label={`Move ${s.name} earlier`}
              className="h-7 rounded border border-border px-2 hover:bg-surface-head"
            >
              Earlier
            </button>
            <button
              type="button"
              onClick={() => onMove?.(1)}
              aria-label={`Move ${s.name} later`}
              className="h-7 rounded border border-border px-2 hover:bg-surface-head"
            >
              Later
            </button>
            <button
              type="button"
              onClick={onRemove}
              aria-label={`Remove ${s.name} from this dashboard`}
              className="ml-auto h-7 rounded px-2 text-text-secondary hover:bg-surface-head"
            >
              Remove
            </button>
          </div>
          {canManage ? <HeadlineForm schedule={s} columns={run?.columns ?? []} /> : null}
        </div>
      ) : null}
      {layout.isError ? (
        <p role="alert" className="text-danger">
          {layout.error instanceof ApiError ? layout.error.message : "That did not work"}
        </p>
      ) : null}
    </section>
  );
}

/** A flag is a warning unless the panel carries its own severity (ADR-0034 polish). */
function FlagBadge() {
  return (
    <span className="shrink-0 rounded-badge border border-warn px-2 py-px text-xs text-warn">
      Flagged
    </span>
  );
}

/** What an empty cell means: "No user parsed" in a user column (the event had none). */
function emptyNote(column: string): string {
  return /user|actor|person|account/i.test(column) ? "No user parsed" : "No value";
}

interface TileCardProps {
  schedule: Schedule;
  value: string | null;
  label: string;
  flag: string | null;
  goodZero: boolean;
  openSql: string | null;
  now: string;
}

/** A tile (ADR-0034 row 2): name, number and what it counts, and the flag state, each on
 * one line. The number opens the rows behind it. */
function TileCard({ schedule: s, value, label, flag, goodZero, openSql, now }: TileCardProps) {
  const last = s.recent[0];
  const state = s.paused
    ? `Paused: ${s.paused_reason ?? "by a person"}`
    : !last
      ? "Not run yet"
      : last.restricted
        ? "Restricted"
        : last.status === "failed"
          ? "Last run failed"
          : null;
  return (
    <section
      id={`panel-${s.schedule_id}`}
      aria-label={s.name}
      className="flex min-w-0 flex-col gap-0.5 rounded-card border border-border bg-surface px-3 py-2 text-sm"
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="min-w-0 flex-1 truncate font-semibold" title={s.name}>
          {s.name}
        </span>
        {flag ? <FlagBadge /> : null}
      </div>
      {state || !last ? (
        <div className="truncate text-text-secondary" title={state ?? undefined}>
          {state}
        </div>
      ) : (
        <>
          <div className="flex min-w-0 items-baseline gap-2">
            {value === null ? (
              <span className="text-text-secondary">No value</span>
            ) : (
              <button
                type="button"
                disabled={!openSql}
                onClick={() => openSql && open(openSql)}
                title={openSql ? "Open the rows behind this number" : undefined}
                className={`text-kpi tabular-nums ${goodZero ? "text-ok" : "text-text"} ${openSql ? "hover:underline" : "cursor-default"}`}
              >
                {formatHeadline(value)}
              </button>
            )}
            <span className="min-w-0 truncate text-text-muted" title={label}>
              {label}
            </span>
          </div>
          <div
            className={`truncate text-xs ${flag ? "text-warn" : goodZero ? "text-ok" : "text-text-muted"}`}
            title={`Last run ${stamp(last.started_at)} UTC`}
          >
            {flag ?? (goodZero ? "Nothing flagged" : since(last.started_at, now))}
          </div>
        </>
      )}
    </section>
  );
}

interface MoveToProps {
  name: string;
  value: string;
  sections: string[];
  onMove: (section: string) => void;
}

const NEW = "\u0000new";

/** Move a panel to another section, or a new one, from the keyboard (DESIGN.md 9). */
function MoveTo({ name, value, sections, onMove }: MoveToProps) {
  const [adding, setAdding] = useState(false);
  const [text, setText] = useState("");
  if (adding) {
    return (
      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) onMove(text.trim());
          setAdding(false);
          setText("");
        }}
      >
        <input
          aria-label={`New section for ${name}`}
          value={text}
          maxLength={60}
          autoFocus
          placeholder="Section name, for example Identity"
          onChange={(e) => setText(e.target.value)}
          className="h-7 min-w-0 flex-1 rounded border border-border-strong bg-inset px-2"
        />
        <button
          type="submit"
          className="h-7 rounded border border-border px-2 hover:bg-surface-head"
        >
          Move
        </button>
        <button type="button" onClick={() => setAdding(false)} className="h-7 rounded px-2">
          Cancel
        </button>
      </form>
    );
  }
  return (
    <label className="flex items-center gap-2">
      <span className="text-text-secondary">Section</span>
      <select
        aria-label={`Move ${name} to section`}
        value={value}
        onChange={(e) => (e.target.value === NEW ? setAdding(true) : onMove(e.target.value))}
        className="h-7 min-w-0 flex-1 rounded border border-border-strong bg-inset px-1"
      >
        <option value="">No section</option>
        {sections.map((x) => (
          <option key={x} value={x}>
            {x}
          </option>
        ))}
        <option value={NEW}>New section…</option>
      </select>
    </label>
  );
}

interface HeadlineFormProps {
  schedule: Schedule;
  columns: string[];
}

/** What the panel's number counts (ADR-0034 row 1), set by the schedule's owner or an
 * admin; it applies from the next run. */
function HeadlineForm({ schedule: s, columns }: HeadlineFormProps) {
  const client = useQueryClient();
  const [kind, setKind] = useState<HeadlineKind>(s.headline_kind ?? "rows");
  const [column, setColumn] = useState(s.headline_column ?? columns[0] ?? "");
  const [label, setLabel] = useState(s.headline_label ?? "");
  const save = useMutation({
    mutationFn: () =>
      api.updateSchedule(s.schedule_id, {
        headline_kind: kind,
        headline_column: kind === "rows" ? "" : column,
        headline_label: label,
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["schedules"] }),
  });
  return (
    <form
      aria-label={`Headline of ${s.name}`}
      className="flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <label className="flex items-center gap-1">
        <span className="text-text-secondary">Number</span>
        <select
          aria-label={`Number shown for ${s.name}`}
          value={kind}
          onChange={(e) => setKind(e.target.value as HeadlineKind)}
          className="h-7 rounded border border-border-strong bg-inset px-1"
        >
          {HEADLINES.map(([k, text]) => (
            <option key={k} value={k}>
              {text}
            </option>
          ))}
        </select>
      </label>
      {kind !== "rows" ? (
        <select
          aria-label={`Column for ${s.name}`}
          value={column}
          onChange={(e) => setColumn(e.target.value)}
          className="h-7 rounded border border-border-strong bg-inset px-1 font-mono"
        >
          {(columns.includes(column) || !column ? columns : [column, ...columns]).map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      ) : null}
      <input
        aria-label={`Label for ${s.name}`}
        value={label}
        maxLength={60}
        placeholder="Label, for example devices"
        onChange={(e) => setLabel(e.target.value)}
        className="h-7 min-w-0 flex-1 basis-40 rounded border border-border-strong bg-inset px-2"
      />
      <button
        type="submit"
        disabled={save.isPending || (kind !== "rows" && !column)}
        className="h-7 rounded border border-border px-2 hover:bg-surface-head disabled:opacity-50"
      >
        Save
      </button>
      {save.isSuccess ? <span className="text-text-muted">From the next run</span> : null}
      {save.isError ? (
        <span role="alert" className="text-danger">
          {save.error instanceof ApiError ? save.error.message : "That did not work"}
        </span>
      ) : null}
    </form>
  );
}

interface BarsProps {
  name: string;
  rows: Cell[][];
  shape: { label: number; value: number };
  valueName: string;
  /** The label column's name, so an address, person, or machine is a link. */
  labelName: string;
  onOpen: (() => void) | null;
}

/** Label and count per row on one shared scale (DESIGN: simple bars, one accent). */
function Bars({ name, rows, shape, valueName, labelName, onOpen }: BarsProps) {
  const labelKind = kindForColumn(labelName);
  const values = rows.map((r) => Number(r[shape.value] ?? 0));
  const top = Math.max(1, ...values);
  return (
    <ul aria-label={`Top values of ${name}`} className="flex flex-col gap-px">
      {rows.map((r, i) => {
        const label = cellText(r[shape.label] ?? null);
        const n = values[i] ?? 0;
        return (
          <li
            key={i}
            {...(onOpen ? onActivate(onOpen) : {})}
            aria-label={`${label}: ${n.toLocaleString()} ${valueName}`}
            className={`relative flex items-center gap-2 rounded px-1.5 py-0.5 ${onOpen ? "cursor-pointer hover:bg-surface-head focus-visible:bg-surface-head" : ""}`}
          >
            <span
              aria-hidden="true"
              className="absolute inset-y-0 left-0 rounded bg-accent-subtle"
              style={{ width: `${Math.max(2, (n / top) * 100)}%` }}
            />
            <span title={label} className="relative min-w-0 flex-1 truncate font-mono">
              {labelKind ? (
                <EntityLink kind={labelKind} value={r[shape.label]} label={label} />
              ) : (
                label
              )}
            </span>
            <span className="relative font-mono tabular-nums text-text-secondary">
              {n.toLocaleString()}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

interface SegmentedProps {
  label: string;
  options: [string, string][];
  value: string;
  onChange: (v: string) => void;
}

function Segmented({ label, options, value, onChange }: SegmentedProps) {
  return (
    <div role="group" aria-label={label} className="flex rounded border border-border">
      {options.map(([v, text]) => (
        <button
          key={v}
          type="button"
          aria-pressed={v === value}
          onClick={() => v !== value && onChange(v)}
          className={`h-6 px-1.5 text-xs first:rounded-l last:rounded-r ${v === value ? "bg-surface-head font-semibold text-text" : "text-text-muted hover:text-text"}`}
        >
          {text}
        </button>
      ))}
    </div>
  );
}
