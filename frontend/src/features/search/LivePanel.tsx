import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ApiError, api, type Cell, type QueryResult } from "@/lib/api";
import { cn } from "@/lib/cn";
import { followLive, type LiveEvent } from "@/lib/liveStream";
import { downloadCsv } from "./ResultsCard";
import { ResultsTable } from "./ResultsTable";

const KEEP = 500; // rows kept in the table, newest at the top (row 1)
const FRESH_MS = 1500;
const BATCHES = 6; // arrivals the "about every" estimate looks at

type Lag = Extract<LiveEvent, { type: "lag" }>["sources"][number];
type State = "starting" | "live" | "paused" | "stopped";

function age(s: number): string {
  if (s < 90) return `${s} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${Math.round(s / 3600)} h`;
}

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)]!;
}

/** "Sources are about 3 min behind; new events arrive about every 30 s": how far behind
 * the sources that send are, and how often batches have come (Loki and connectors pull,
 * so events come in bursts, not one by one). Null until there is something to say. */
export function cadenceLine(lag: Lag[] | null, arrivals: number[]): string | null {
  const behind = median((lag ?? []).flatMap((l) => (l.age_s === null ? [] : [l.age_s])));
  const gaps = arrivals.slice(1).map((t, i) => (t - arrivals[i]!) / 1000);
  const every = gaps.length >= 2 ? median(gaps) : null;
  const parts = [];
  if (behind !== null && behind >= 30) parts.push(`Sources are about ${age(behind)} behind`);
  if (every !== null && every >= 5)
    parts.push(`new events arrive about every ${age(Math.round(every))}`);
  if (!parts.length) return null;
  const text = parts.join("; ");
  return `${text[0]!.toUpperCase()}${text.slice(1)}.`;
}

/** A connector pulls every few minutes: silent for less than 2 of its pulls is normal;
 * anything else is late after 2 minutes. */
function late(l: Lag): boolean {
  if (l.age_s === null) return true;
  return l.age_s > (l.pull_every_s ? 2 * l.pull_every_s : 120);
}

interface LivePanelProps {
  sql: string;
  sources: string[];
  /** Start this many minutes back, so the table is not empty while sources catch up. */
  fillMinutes?: number;
  onClose: () => void;
}

/** Live mode on Search (ADR-0036): follows new event rows of the query in the editor.
 * Pause ends the stream on the server and keeps the cursor; Resume starts a new one from
 * it; Stop ends Live. While a row is open or the table is scrolled down, new rows wait in
 * an "N new" bar so nothing moves under the reader. Nothing runs a model. */
export function LivePanel({ sql, sources, fillMinutes = 0, onClose }: LivePanelProps) {
  const client = useQueryClient();
  const [state, setState] = useState<State>("starting");
  const [columns, setColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<Cell[][]>([]);
  const [count, setCount] = useState(0);
  const [since, setSince] = useState<string | null>(null);
  const [lag, setLag] = useState<Lag[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [ended, setEnded] = useState<string | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  // Rows that arrived while the reader was looking (a row open, or scrolled down).
  const [held, setHeld] = useState<Cell[][]>([]);
  const [rowOpen, setRowOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const holding = useRef(false);
  holding.current = rowOpen || scrolled;
  const [arrivals, setArrivals] = useState<number[]>([]);
  const pane = useRef<HTMLDivElement>(null);
  const cursor = useRef<{ t: string; ids: string[] } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const streams = useQuery({
    queryKey: ["live-streams"],
    queryFn: api.liveStreams,
    enabled: refused !== null,
  });
  const stopOther = useMutation({
    mutationFn: api.stopLiveStream,
    onSuccess: () => void client.invalidateQueries({ queryKey: ["live-streams"] }),
  });

  const start = (resume: boolean) => {
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    setState("starting");
    setEnded(null);
    setRefused(null);
    setNotice(null);
    const c = resume ? cursor.current : null;
    followLive({
      sql,
      sources,
      since: c?.t,
      after: c?.ids,
      fillMinutes: resume ? 0 : fillMinutes,
      signal: ctl.signal,
      onEvent: (e) => {
        if (e.type === "start") {
          setState("live");
          if (!resume) setSince(e.since);
        } else if (e.type === "rows") {
          cursor.current = e.cursor;
          setColumns(e.columns);
          const idAt = e.columns.indexOf("event_id");
          const newest = [...e.rows].reverse();
          setCount((n) => n + e.rows.length);
          if (e.rows.length) setArrivals((a) => [...a, Date.now()].slice(-BATCHES));
          if (holding.current) {
            setHeld((h) => [...newest, ...h].slice(0, KEEP));
            return;
          }
          setRows((old) => [...newest, ...old].slice(0, KEEP));
          if (idAt >= 0) {
            const ids = new Set(e.rows.map((r) => String(r[idAt])));
            setFresh(ids);
            window.setTimeout(() => setFresh(new Set()), FRESH_MS);
          }
        } else if (e.type === "lag") {
          setLag(e.sources);
        } else if (e.type === "notice") {
          setNotice(e.message);
        } else if (e.type === "end") {
          setEnded(e.message);
          setState(e.reason === "time_limit" ? "paused" : "stopped");
        }
      },
    })
      .then(() => {
        if (abort.current === ctl)
          setState((s) => (s === "live" || s === "starting" ? "paused" : s));
      })
      .catch((err: unknown) => {
        if (ctl.signal.aborted) return;
        setState("stopped");
        if (err instanceof ApiError && err.status === 409) setRefused(err.message);
        else setEnded(err instanceof Error ? err.message : "Live could not start");
      });
  };

  useEffect(() => {
    start(false);
    return () => abort.current?.abort();
    // Starts once per mount; the parent remounts for a new query.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pause = () => {
    abort.current?.abort();
    abort.current = null;
    setState("paused");
  };
  const stop = () => {
    abort.current?.abort();
    abort.current = null;
    onClose();
  };
  const result: QueryResult = {
    columns,
    rows,
    row_count: rows.length,
    truncated: count > rows.length,
    elapsed_ms: 0,
    executed_sql: sql,
    sources,
  };
  const sinceText = since ? `${since.slice(11, 16)} UTC` : "now";
  const cadence = cadenceLine(lag, arrivals);
  const showHeld = () => {
    setRows((old) => [...held, ...old].slice(0, KEEP));
    setHeld([]);
    pane.current?.scrollTo({ top: 0 });
    setScrolled(false);
  };
  return (
    <section
      aria-label="Live results"
      className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-card border border-border bg-surface"
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border bg-surface-head px-3 py-2 text-sm">
        <span className="font-semibold">
          {state === "live"
            ? `Live since ${sinceText}`
            : state === "paused"
              ? `Paused. Live since ${sinceText}`
              : state === "starting"
                ? "Starting live…"
                : "Live stopped"}
        </span>
        {lag && !lag.length ? (
          <span className="text-warn">No source you can read sent events in the last day</span>
        ) : null}
        {lag?.length ? (
          <span aria-label="Freshness by source" className="text-text-muted">
            {lag.map((l, i) => (
              <span key={l.source} className={cn(late(l) && "text-warn")}>
                {i ? ", " : ""}
                {l.source} {l.age_s === null ? "no events" : age(l.age_s)}
                {l.pull_every_s ? ` (pulls every ${age(l.pull_every_s)})` : ""}
              </span>
            ))}
          </span>
        ) : null}
        <span className="ml-auto flex gap-2">
          {state === "live" || state === "starting" ? (
            <button
              type="button"
              onClick={pause}
              className="h-7 rounded border border-border px-2.5 hover:bg-surface"
            >
              Pause
            </button>
          ) : state === "paused" ? (
            <button
              type="button"
              onClick={() => start(true)}
              className="h-7 rounded border border-border px-2.5 hover:bg-surface"
            >
              Resume
            </button>
          ) : null}
          <button
            type="button"
            onClick={stop}
            className="h-7 rounded border border-border px-2.5 hover:bg-surface"
          >
            Stop
          </button>
          <button
            type="button"
            disabled={!rows.length}
            onClick={() => void downloadCsv({ sql, start: since ?? undefined, sources })}
            className="h-7 rounded border border-border px-2.5 hover:bg-surface disabled:opacity-50"
          >
            Export
          </button>
        </span>
      </div>
      <p className="border-b border-border px-3 py-1 text-sm text-text-muted">
        {count.toLocaleString()} {count === 1 ? "event" : "events"}, newest first
        {count > rows.length + held.length ? ` (the newest ${KEEP} are kept here)` : ""}
        {cadence && rows.length ? `. ${cadence}` : ""}
      </p>
      {held.length ? (
        <button
          type="button"
          onClick={showHeld}
          className="border-b border-border bg-accent-subtle px-3 py-1.5 text-left text-sm text-accent-text hover:underline"
        >
          {held.length.toLocaleString()} new {held.length === 1 ? "event" : "events"}. Show
          {rowOpen ? " (the open row stays open)" : ""}
        </button>
      ) : null}
      {notice ? (
        <p role="status" className="border-b border-border px-3 py-1.5 text-sm text-text-secondary">
          {notice}
        </p>
      ) : null}
      {ended ? (
        <p role="status" className="border-b border-border px-3 py-1.5 text-sm text-warn">
          {ended}
        </p>
      ) : null}
      {refused ? (
        <div role="alert" className="flex flex-col gap-1 border-b border-border px-3 py-2 text-sm">
          <span className="text-warn">{refused}</span>
          <ul className="flex flex-col gap-1">
            {(streams.data ?? []).map((s) => (
              <li key={s.stream_id} className="flex items-center gap-2">
                <span>{s.label}</span>
                <button
                  type="button"
                  onClick={() => stopOther.mutate(s.stream_id)}
                  className="text-accent-text hover:underline"
                  aria-label={`Stop ${s.label}`}
                >
                  Stop
                </button>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => start(false)}
            className="h-7 self-start rounded border border-border px-2.5 hover:bg-surface-head"
          >
            Try again
          </button>
        </div>
      ) : null}
      {rows.length ? (
        <div
          ref={pane}
          onScroll={(e) => setScrolled(e.currentTarget.scrollTop > 4)}
          className="min-h-0 flex-1 overflow-y-auto"
        >
          <ResultsTable
            result={result}
            view="parsed"
            compact
            fresh={fresh}
            onOpenChange={setRowOpen}
          />
        </div>
      ) : state === "live" ? (
        <p className="px-3 py-6 text-center text-sm text-text-secondary">
          Waiting for new events. They appear here as they arrive.
          {cadence ? ` ${cadence}` : ""}
        </p>
      ) : null}
    </section>
  );
}
