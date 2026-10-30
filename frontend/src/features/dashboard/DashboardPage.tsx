import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  ApiError,
  api,
  type DashboardLayout,
  type Dashboard,
  type DashboardPanel,
  type Schedule,
  type User,
} from "@/lib/api";
import { navigate } from "@/lib/route";
import { takeDashboardScroll } from "@/lib/drill";
import { rangeWords } from "./headline";
import { stamp } from "@/features/overview/time";
import { currentDashboard, rememberDashboard } from "./choice";
import { AiWatch } from "./AiWatch";
import { Sections } from "./Sections";
import { WINDOWS, daysOf, rangeText as windowRange, readWindow, saveWindow } from "./pageWindow";
import type { PageWindow } from "@/lib/api";
import { cn } from "@/lib/cn";
import { AttentionBanner, SourcesLine } from "./Attention";
import { layoutOf, placed, sectionAdded, sectionRemoved, sectionStepped, stepped } from "./layout";
import { SchedulePanel } from "./SchedulePanel";

interface DashboardPageProps {
  me?: User | null;
}

/** Grid spans: one column on phones, two on tablets, six from wide screens. A tile is a
 * sixth: detection-style searches with a number and a flag (ADR-0034 row 2). */
const SPAN: Record<DashboardPanel["size"], string> = {
  tile: "md:col-span-1 xl:col-span-1",
  third: "md:col-span-1 xl:col-span-2",
  half: "md:col-span-1 xl:col-span-3",
  full: "md:col-span-2 xl:col-span-6",
};

function span(p: DashboardPanel, cards: number, editing: boolean): string {
  if (editing) return SPAN[p.size];
  if (cards === 1) return SPAN.full;
  if (cards === 2 && (p.size === "third" || p.size === "tile")) return SPAN.half;
  return SPAN[p.size];
}

/** Named dashboards of schedule panels (ADR-0034): pick one, see what needs attention,
 * then the panels by section. The owner or an admin edits the layout. */
export function DashboardPage({ me = null }: DashboardPageProps) {
  const client = useQueryClient();
  const isAdmin = !me || me.role === "admin";
  const canCreate = !me || me.role !== "auditor";
  const boards = useQuery({ queryKey: ["dashboards"], queryFn: api.dashboards });
  const schedules = useQuery({
    queryKey: ["schedules"],
    queryFn: api.schedules,
    refetchInterval: 60_000,
  });
  const [picked, setPicked] = useState<string | null>(currentDashboard);
  const [editing, setEditing] = useState(false);
  const [win, setWin] = useState<PageWindow>(readWindow);
  // Back from a drill-through returns to where the reader was (ADR-0039 row 6): the page
  // grows as sections load, so try for up to two seconds.
  useEffect(() => {
    const y = takeDashboardScroll();
    if (y === null || y <= 0) return;
    let frame = 0;
    const until = Date.now() + 2000;
    const step = () => {
      const fits = document.documentElement.scrollHeight - window.innerHeight >= y;
      if (fits || Date.now() > until) window.scrollTo(0, y);
      else frame = window.requestAnimationFrame(step);
    };
    frame = window.requestAnimationFrame(step);
    return () => window.cancelAnimationFrame(frame);
  }, []);
  const list = boards.data ?? [];
  const board = list.find((d) => d.dashboard_id === picked) ?? list[0] ?? null;
  const byId = new Map((schedules.data ?? []).map((s) => [s.schedule_id, s]));
  const pick = (id: string) => {
    setPicked(id);
    rememberDashboard(id);
    setEditing(false);
  };
  const refresh = () => client.invalidateQueries({ queryKey: ["dashboards"] });
  const create = useMutation({
    mutationFn: () => api.createDashboard(nextName(list)),
    onSuccess: async (d) => {
      await refresh();
      pick(d.dashboard_id);
      setEditing(true);
    },
  });
  // Every layout change (drag and drop, keyboard moves, sections) sends the whole layout.
  const arrange = useMutation({
    mutationFn: (next: DashboardLayout) => api.setLayout(board?.dashboard_id ?? "", next),
    onSuccess: refresh,
  });
  const rename = useMutation({
    mutationFn: (v: { from: string; to: string }) =>
      api.renameSection(board?.dashboard_id ?? "", v.from, v.to),
    onSuccess: refresh,
  });
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const layout = board ? layoutOf(board) : [];
  const byPanel = new Map((board?.panels ?? []).map((p) => [p.schedule_id, p]));
  const drop = (section: string, index?: number) => {
    if (dragging) arrange.mutate(placed(layout, dragging, section, index));
    setDragging(null);
    setOver(null);
  };
  const remove = useMutation({
    mutationFn: (scheduleId: string) => api.removePanel(board?.dashboard_id ?? "", scheduleId),
    onSuccess: refresh,
  });
  const move = (scheduleId: string, step: -1 | 1) =>
    arrange.mutate(stepped(layout, scheduleId, step));
  // The page header says which range the panels cover and when they last ran.
  const onBoard = board
    ? board.panels.map((p) => byId.get(p.schedule_id)).filter((x): x is Schedule => Boolean(x))
    : [];
  // The range only when every panel shares it; panels with different ranges say their own.
  const ranges = [...new Set(onBoard.map((x) => rangeWords(x.lookback_minutes)))];
  const rangeText = ranges.length === 1 ? ranges[0] : null;
  const lastRun = onBoard
    .map((x) => x.recent[0]?.started_at)
    .filter((t): t is string => Boolean(t))
    .sort()
    .at(-1);
  const cell = (p: DashboardPanel) => {
    const s = byId.get(p.schedule_id);
    if (s && board)
      return (
        <SchedulePanel
          schedule={s}
          panel={p}
          dashboardId={board.dashboard_id}
          editing={editing}
          canManage={s.mine || isAdmin}
          onMove={(step) => move(p.schedule_id, step)}
          onRemove={() => remove.mutate(p.schedule_id)}
          sections={board.sections}
          onMoveTo={(section) => arrange.mutate(placed(layout, p.schedule_id, section))}
        />
      );
    if (!schedules.isSuccess) return null;
    return (
      <section
        aria-label="Restricted panel"
        className="flex h-full flex-col gap-1 rounded-card border border-border bg-surface p-3 text-sm"
      >
        <div className="font-semibold">Restricted</div>
        <p className="text-text-secondary">This panel shows a schedule you cannot see.</p>
      </section>
    );
  };
  const error =
    boards.error ??
    schedules.error ??
    arrange.error ??
    rename.error ??
    remove.error ??
    create.error;

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      {/* Compact header (F62): title, picker, New dashboard, Edit layout, and when it was
          updated, on one row; no band under the title. */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-5 pt-3">
        <h1 className="mr-2 text-lg font-semibold">{board?.name ?? "Dashboard"}</h1>
        {/* One time window for the page (ADR-0038 edit 10). */}
        <div
          role="group"
          aria-label="Time window"
          className="flex rounded border border-border text-sm"
        >
          {WINDOWS.map((w) => (
            <button
              key={w.id}
              type="button"
              aria-pressed={win === w.id}
              onClick={() => {
                setWin(w.id);
                saveWindow(w.id);
              }}
              className={cn(
                "h-8 px-2.5",
                win === w.id
                  ? "bg-accent-subtle font-semibold text-accent-text"
                  : "text-text-secondary hover:text-text",
              )}
            >
              {w.label}
            </button>
          ))}
        </div>
        <span className="mr-2 text-sm text-text-muted">{windowRange(win)}</span>
        {list.length > 1 ? (
          <select
            aria-label="Dashboard"
            value={board?.dashboard_id ?? ""}
            onChange={(e) => pick(e.target.value)}
            className="h-8 rounded border border-border-strong bg-inset px-2 text-sm"
          >
            {list.map((d) => (
              <option key={d.dashboard_id} value={d.dashboard_id}>
                {d.name}
                {d.shared && !d.mine ? " (shared)" : ""}
              </option>
            ))}
          </select>
        ) : null}
        {canCreate ? (
          <button
            type="button"
            onClick={() => create.mutate()}
            disabled={create.isPending}
            className="h-8 rounded px-2 text-sm text-accent-text hover:bg-surface-head"
          >
            New dashboard
          </button>
        ) : null}
        {board?.can_edit ? (
          <button
            type="button"
            aria-pressed={editing}
            onClick={() => setEditing((v) => !v)}
            className={`h-8 rounded border px-2 text-sm ${editing ? "border-accent bg-accent-subtle" : "border-border hover:bg-surface-head"}`}
          >
            {editing ? "Done editing" : "Edit layout"}
          </button>
        ) : null}
        {board ? (
          <span
            className="ml-auto text-sm text-text-secondary"
            title={lastRun ? `Newest run ${stamp(lastRun)} UTC` : undefined}
          >
            {[
              rangeText,
              `${board.panels.length} ${board.panels.length === 1 ? "panel" : "panels"}`,
              board.shared ? "shared" : null,
            ]
              .filter(Boolean)
              .join(", ")}
          </span>
        ) : null}
      </div>
      <div className="flex flex-col gap-3 px-5 py-3">
        {/* Order (F62): what needs me (only when something does), AI Watch, my panels,
            then sources in one line. */}
        <AttentionBanner />
        <AiWatch days={daysOf(win)} />
        <Sections window={win} />
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error instanceof ApiError ? error.message : "Could not load"}
          </p>
        ) : null}
        {board && editing ? (
          <BoardSettings
            board={board}
            schedules={schedules.data ?? []}
            onAddSection={(name) => arrange.mutate(sectionAdded(layout, name))}
            onDeleted={() => {
              setEditing(false);
              setPicked(null);
            }}
          />
        ) : null}
        {boards.isSuccess && (!board || board.panels.length === 0) ? (
          <div className="rounded-card border border-border bg-surface px-3 py-8 text-center text-sm">
            <p className="font-semibold">No panels yet</p>
            <p className="text-text-secondary">
              Each scheduled saved search or rule can be a panel here. Schedule one, or use Add to
              dashboard on Search.
            </p>
            <button
              type="button"
              className="mt-2 rounded px-2 py-1 text-accent-text hover:bg-surface-head"
              onClick={() => navigate("schedules")}
            >
              Go to Schedules
            </button>
          </div>
        ) : null}
        {board
          ? layout
              .filter((sec) => sec.schedule_ids.length > 0 || (editing && sec.name))
              .map((sec, si, shown) => {
                const panels = sec.schedule_ids
                  .map((id) => byPanel.get(id))
                  .filter((p): p is DashboardPanel => Boolean(p));
                const tiles = panels.filter((p) => p.size === "tile");
                const cards = panels.filter((p) => editing || p.size !== "tile");
                const dropHere = editing && dragging !== null;
                return (
                  <section
                    key={sec.name || "(none)"}
                    aria-label={sec.name || "Panels"}
                    onDragOver={(e) => {
                      if (!dropHere) return;
                      e.preventDefault();
                      setOver(`section:${sec.name}`);
                    }}
                    onDrop={(e) => {
                      e.preventDefault();
                      drop(sec.name);
                    }}
                    className={`flex flex-col gap-2 rounded ${dropHere && over === `section:${sec.name}` ? "outline outline-2 outline-accent" : ""}`}
                  >
                    {sec.name ? (
                      <SectionHeader
                        name={sec.name}
                        count={panels.length}
                        editing={editing}
                        first={si === (shown[0]?.name === "" ? 1 : 0)}
                        last={si === shown.length - 1}
                        onRename={(to) => rename.mutate({ from: sec.name, to })}
                        onMove={(step) => arrange.mutate(sectionStepped(layout, sec.name, step))}
                        onDelete={() => arrange.mutate(sectionRemoved(layout, sec.name))}
                      />
                    ) : editing ? (
                      <h2 className="border-b border-border pb-1 text-sm font-semibold text-text-secondary">
                        No section
                      </h2>
                    ) : null}
                    {tiles.length && !editing ? (
                      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
                        {tiles.map((p) => (
                          <div key={p.schedule_id} className="min-w-0">
                            {cell(p)}
                          </div>
                        ))}
                      </div>
                    ) : null}
                    {cards.length ? (
                      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-6">
                        {cards.map((p, i) => (
                          // No gaps: one card alone fills the row, two share it half and half.
                          <div
                            key={p.schedule_id}
                            draggable={editing}
                            onDragStart={(e) => {
                              e.dataTransfer.effectAllowed = "move";
                              e.dataTransfer.setData("text/plain", p.schedule_id);
                              setDragging(p.schedule_id);
                            }}
                            onDragEnd={() => {
                              setDragging(null);
                              setOver(null);
                            }}
                            onDragOver={(e) => {
                              if (!dropHere) return;
                              e.preventDefault();
                              e.stopPropagation();
                              setOver(`panel:${p.schedule_id}`);
                            }}
                            onDrop={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              drop(sec.name, sec.schedule_ids.indexOf(p.schedule_id));
                            }}
                            className={`min-w-0 ${span(p, cards.length, editing)} ${editing ? "cursor-grab" : ""} ${dragging === p.schedule_id ? "opacity-50" : ""} ${dropHere && over === `panel:${p.schedule_id}` ? "rounded-card outline outline-2 outline-accent" : ""}`}
                            data-index={i}
                          >
                            {cell(p)}
                          </div>
                        ))}
                      </div>
                    ) : editing ? (
                      <p className="rounded-card border border-dashed border-border px-3 py-4 text-center text-sm text-text-muted">
                        Drag panels here, or use Section on a panel
                      </p>
                    ) : null}
                  </section>
                );
              })
          : null}
        <SourcesLine />
      </div>
    </div>
  );
}

function nextName(list: Dashboard[]): string {
  const taken = new Set(list.map((d) => d.name));
  for (let i = 1; ; i++) {
    const name = i === 1 ? "New dashboard" : `New dashboard ${i}`;
    if (!taken.has(name)) return name;
  }
}

interface BoardSettingsProps {
  board: Dashboard;
  schedules: Schedule[];
  onAddSection: (name: string) => void;
  onDeleted: () => void;
}

/** Name, sharing, adding panels, and deleting the dashboard (edit mode only). */
function BoardSettings({ board, schedules, onAddSection, onDeleted }: BoardSettingsProps) {
  const client = useQueryClient();
  const [name, setName] = useState(board.name);
  const [adding, setAdding] = useState("");
  const [section, setSection] = useState("");
  const [confirming, setConfirming] = useState(false);
  const refresh = () => client.invalidateQueries({ queryKey: ["dashboards"] });
  const save = useMutation({
    mutationFn: (body: { name?: string; shared?: boolean }) =>
      api.updateDashboard(board.dashboard_id, body),
    onSuccess: refresh,
  });
  const add = useMutation({
    mutationFn: (scheduleId: string) => api.setPanel(board.dashboard_id, scheduleId, {}),
    onSuccess: async () => {
      setAdding("");
      await refresh();
    },
  });
  const del = useMutation({
    mutationFn: () => api.deleteDashboard(board.dashboard_id),
    onSuccess: async () => {
      onDeleted();
      await refresh();
    },
  });
  const on = new Set(board.panels.map((p) => p.schedule_id));
  const available = schedules.filter((s) => !on.has(s.schedule_id));
  const failure = save.error ?? add.error ?? del.error;
  return (
    <section
      aria-label="Dashboard settings"
      className="flex flex-col gap-3 rounded-card border border-accent bg-surface p-3 text-sm"
    >
      <div className="flex flex-wrap items-end gap-3">
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim() && name.trim() !== board.name) save.mutate({ name: name.trim() });
          }}
        >
          <label className="flex flex-col gap-1">
            <span className="text-text-secondary">Name</span>
            <input
              aria-label="Dashboard name"
              value={name}
              maxLength={80}
              onChange={(e) => setName(e.target.value)}
              className="h-8 w-56 rounded border border-border-strong bg-inset px-2"
            />
          </label>
          <button
            type="submit"
            className="h-8 rounded border border-border px-2 hover:bg-surface-head"
          >
            Rename
          </button>
        </form>
        <label className="flex h-8 items-center gap-2">
          <input
            type="checkbox"
            checked={board.shared}
            onChange={(e) => save.mutate({ shared: e.target.checked })}
          />
          Shared with everyone (each viewer still sees only what their sources allow)
        </label>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-text-secondary">Add a panel</span>
          <select
            aria-label="Schedule to add"
            value={adding}
            onChange={(e) => setAdding(e.target.value)}
            className="h-8 min-w-56 rounded border border-border-strong bg-inset px-2"
          >
            <option value="">
              {available.length ? "Pick a schedule" : "Every schedule you can see is here"}
            </option>
            {available.map((s) => (
              <option key={s.schedule_id} value={s.schedule_id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={!adding || add.isPending}
          onClick={() => add.mutate(adding)}
          className="h-8 rounded border border-border px-2 hover:bg-surface-head disabled:opacity-50"
        >
          Add panel
        </button>
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (section.trim()) onAddSection(section.trim());
            setSection("");
          }}
        >
          <label className="flex flex-col gap-1">
            <span className="text-text-secondary">Add a section</span>
            <input
              aria-label="New section name"
              value={section}
              maxLength={60}
              placeholder="For example Identity"
              onChange={(e) => setSection(e.target.value)}
              className="h-8 w-48 rounded border border-border-strong bg-inset px-2"
            />
          </label>
          <button
            type="submit"
            disabled={!section.trim() || board.sections.includes(section.trim())}
            className="h-8 rounded border border-border px-2 hover:bg-surface-head disabled:opacity-50"
          >
            Add section
          </button>
        </form>
        <span className="ml-auto">
          {confirming ? (
            <span className="flex items-center gap-2">
              <span>Delete this dashboard? Its schedules keep running.</span>
              <button
                type="button"
                onClick={() => del.mutate()}
                className="h-8 rounded bg-danger px-2 font-semibold text-white"
              >
                Delete dashboard
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className="h-8 rounded px-2"
              >
                Keep it
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="h-8 rounded px-2 text-text-secondary hover:bg-surface-head"
            >
              Delete dashboard
            </button>
          )}
        </span>
      </div>
      {failure ? (
        <p role="alert" className="text-danger">
          {failure instanceof ApiError ? failure.message : "That did not work"}
        </p>
      ) : null}
    </section>
  );
}

interface SectionHeaderProps {
  name: string;
  count: number;
  editing: boolean;
  first: boolean;
  last: boolean;
  onRename: (to: string) => void;
  onMove: (step: -1 | 1) => void;
  onDelete: () => void;
}

/** A section's heading; in Edit layout also Rename, Move up, Move down, and Delete (its
 * panels move to No section; nothing is deleted but the heading). */
function SectionHeader(props: SectionHeaderProps) {
  const { name, count, editing, first, last, onRename, onMove, onDelete } = props;
  const [renaming, setRenaming] = useState(false);
  const [text, setText] = useState(name);
  const [confirming, setConfirming] = useState(false);
  return (
    <div className="flex flex-wrap items-baseline gap-2 border-b border-border pb-1">
      {renaming ? (
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim() && text.trim() !== name) onRename(text.trim());
            setRenaming(false);
          }}
        >
          <input
            aria-label={`New name for section ${name}`}
            value={text}
            maxLength={60}
            autoFocus
            onChange={(e) => setText(e.target.value)}
            className="h-7 w-48 rounded border border-border-strong bg-inset px-2 text-sm"
          />
          <button type="submit" className="h-7 rounded border border-border px-2 text-sm">
            Save
          </button>
          <button type="button" onClick={() => setRenaming(false)} className="h-7 px-2 text-sm">
            Cancel
          </button>
        </form>
      ) : (
        <h2 className="flex items-baseline gap-2 text-base font-semibold">
          {name}
          <span className="text-sm font-normal text-text-muted">{count}</span>
        </h2>
      )}
      {editing && !renaming ? (
        <span className="ml-auto flex flex-wrap items-center gap-1 text-sm">
          <button
            type="button"
            onClick={() => {
              setText(name);
              setRenaming(true);
            }}
            aria-label={`Rename section ${name}`}
            className="h-7 rounded px-2 hover:bg-surface-head"
          >
            Rename
          </button>
          <button
            type="button"
            disabled={first}
            onClick={() => onMove(-1)}
            aria-label={`Move section ${name} up`}
            className="h-7 rounded px-2 hover:bg-surface-head disabled:opacity-40"
          >
            Move up
          </button>
          <button
            type="button"
            disabled={last}
            onClick={() => onMove(1)}
            aria-label={`Move section ${name} down`}
            className="h-7 rounded px-2 hover:bg-surface-head disabled:opacity-40"
          >
            Move down
          </button>
          {confirming ? (
            <>
              <span className="text-text-secondary">Panels move to No section.</span>
              <button
                type="button"
                onClick={onDelete}
                className="h-7 rounded border border-danger px-2 text-danger"
              >
                Delete section
              </button>
              <button type="button" onClick={() => setConfirming(false)} className="h-7 px-2">
                Keep it
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              aria-label={`Delete section ${name}`}
              className="h-7 rounded px-2 text-text-secondary hover:bg-surface-head"
            >
              Delete
            </button>
          )}
        </span>
      ) : null}
    </div>
  );
}
