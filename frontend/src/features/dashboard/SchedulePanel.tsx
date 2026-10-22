import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { KeyboardEvent } from "react";
import { api, type Cell, type Schedule } from "@/lib/api";
import { navigate } from "@/lib/route";
import { eventsSql, seedSearch } from "@/lib/searchSeed";
import { cronLabel, counts, fillSql } from "@/features/schedules/schedule";
import {
  barShape,
  cellText,
  COLUMNS_AT,
  WIDTH_LABEL,
  type PanelView,
  type PanelWidth,
} from "./panelShape";
import { Sparkline } from "./Sparkline";

const TOP_ROWS = 5;
const TOP_BARS = 10;
const WIDTHS: PanelWidth[] = ["third", "half", "full"];

interface SchedulePanelProps {
  schedule: Schedule;
  /** The owner or an admin: may change how the panel is shown (for everyone). */
  canManage: boolean;
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

/** One schedule on the Dashboard (SPEC 5.5): last run, count, trend, flag, and the top
 * rows as a table or, for a summary result, as bars. */
export function SchedulePanel({ schedule: s, canManage }: SchedulePanelProps) {
  const client = useQueryClient();
  const last = s.recent[0];
  const readable = last && last.status === "ok" && !last.restricted;
  const width = (s.panel_width ?? "third") as PanelWidth;
  const detail = useQuery({
    queryKey: ["schedule-run", s.schedule_id, last?.run_id],
    queryFn: () => api.scheduleRun(s.schedule_id, last?.run_id ?? ""),
    enabled: Boolean(readable),
  });
  const searches = useQuery({
    queryKey: ["searches"],
    queryFn: api.searches,
    enabled: s.kind === "search",
  });
  const layout = useMutation({
    mutationFn: (body: { panel_width?: PanelWidth; panel_view?: PanelView }) =>
      api.updateSchedule(s.schedule_id, body),
    onSuccess: () => client.invalidateQueries({ queryKey: ["schedules"] }),
  });
  const run = detail.data;
  const shape = run ? barShape(run.columns, run.sample.slice(0, TOP_BARS)) : null;
  const view: PanelView = shape && s.panel_view === "bars" ? "bars" : "table";

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

  return (
    <section
      aria-label={s.name}
      className="flex h-full min-w-0 flex-col gap-2 rounded-card border border-border bg-surface p-3 text-sm"
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold" title={s.name}>
            {s.name}
          </div>
          <div className="text-text-muted">
            {s.kind === "search" ? "Saved search" : "Rule"} · {cronLabel(s.cron)}
          </div>
        </div>
        {last?.flagged && !last.restricted ? (
          <span className="rounded-badge bg-sev-high-bg px-2 py-px text-xs text-sev-high-text">
            Flagged
          </span>
        ) : null}
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
          <div className="flex items-end justify-between gap-3">
            <div>
              <div className="text-kpi">{last.row_count ?? 0}</div>
              <div className="text-text-muted">
                {s.kind === "rule" ? "matches" : "rows"} ·{" "}
                {last.started_at.slice(0, 16).replace("T", " ")}
              </div>
            </div>
            <Sparkline
              values={counts(s.recent)}
              label={`Counts of the last ${s.recent.length} runs`}
            />
          </div>
          {last.flagged && last.flag_reason ? (
            <p className="text-sev-high-text">{last.flag_reason}</p>
          ) : null}
          {last.parser_change ? (
            <p role="note" className="text-warn">
              {last.parser_change}
            </p>
          ) : null}
          {run && shape && view === "bars" ? (
            <Bars
              name={s.name}
              rows={run.sample.slice(0, TOP_BARS)}
              shape={shape}
              valueName={run.columns[shape.value] ?? "count"}
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
                          <td key={j} title={cellText(v)} className="truncate px-2 py-1 font-mono">
                            {cellText(v)}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
          {run && view === "table" && shown < run.columns.length ? (
            <p className="text-xs text-text-muted">
              Showing {shown} of {run.columns.length} columns. Open the result for all of them.
            </p>
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
            Open in Search
          </button>
        ) : null}
        {canManage ? (
          <div className="ml-auto flex items-center gap-2">
            {shape ? (
              <Segmented
                label={`View of ${s.name}`}
                options={[
                  ["table", "Table"],
                  ["bars", "Bars"],
                ]}
                value={view}
                onChange={(v) => layout.mutate({ panel_view: v as PanelView })}
              />
            ) : null}
            <Segmented
              label={`Width of ${s.name}`}
              options={WIDTHS.map((w) => [w, WIDTH_LABEL[w]])}
              value={width}
              onChange={(v) => layout.mutate({ panel_width: v as PanelWidth })}
            />
          </div>
        ) : null}
      </div>
      {layout.isError ? (
        <p role="alert" className="text-danger">
          {(layout.error as Error).message}
        </p>
      ) : null}
    </section>
  );
}

interface BarsProps {
  name: string;
  rows: Cell[][];
  shape: { label: number; value: number };
  valueName: string;
  onOpen: (() => void) | null;
}

/** Label and count per row on one shared scale (DESIGN: simple bars, one accent). */
function Bars({ name, rows, shape, valueName, onOpen }: BarsProps) {
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
              {label}
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
