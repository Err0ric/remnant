import { PinButton } from "@/components/PinButton";
import { About } from "@/components/About";
import { EmptyState } from "@/components/EmptyState";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api, type SavedSearch, type Schedule, type User } from "@/lib/api";
import { navigate, pathFor, setFragment, useSection } from "@/lib/route";
import { targetIn } from "@/lib/pins";
import { cronLabel } from "@/features/schedules/schedule";
import { seedSchedule } from "@/lib/scheduleSeed";
import { seedSearch } from "@/lib/searchSeed";
import { takeSavedSeed } from "@/lib/savedSeed";
import { AddToDashboardPanel } from "@/features/dashboard/AddToDashboard";
import { SearchRunner } from "./SearchRunner";
import { AUDITOR_SQL_OFF } from "@/lib/sqlAccess";
import { useViewer } from "@/lib/viewer";

interface SavedSearchesPageProps {
  me: User | null;
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/yaml" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export function SavedSearchesPage({ me }: SavedSearchesPageProps) {
  const client = useQueryClient();
  const searches = useQuery({ queryKey: ["searches"], queryFn: api.searches });
  // The schedules this person may see, to say which searches run on one (ADR-0052 3.3).
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: api.schedules });
  const scheduledBy = new Map<string, Schedule[]>();
  for (const sch of schedules.data ?? []) {
    if (sch.kind !== "search") continue;
    scheduledBy.set(sch.target_id, [...(scheduledBy.get(sch.target_id) ?? []), sch]);
  }
  const [chosen, setRunning] = useState<SavedSearch | null>(null);
  // A search picked in the command palette opens its runner once the list has loaded.
  const [seeded, setSeeded] = useState(takeSavedSeed);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [toDashboard, setToDashboard] = useState<SavedSearch | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const myId = me?.user_id ?? "local";
  const isAdmin = !me || me.role === "admin";
  const canAuthor = !me || me.role !== "auditor";
  // D220: an Auditor runs saved searches only while an admin allows Auditors SQL.
  const { canRunSql = true } = useViewer();
  const refresh = () => client.invalidateQueries({ queryKey: ["searches"] });

  const remove = useMutation({
    mutationFn: api.deleteSearch,
    onSuccess: async () => {
      setConfirming(null);
      await refresh();
    },
  });
  const importer = useMutation({
    mutationFn: api.importSearch,
    onSuccess: async (s) => {
      setNotice(`Imported ${s.id} as a private search.`);
      await refresh();
    },
  });
  const verifier = useMutation({
    mutationFn: (s: SavedSearch) => api.verifySearch(s.id, !s.verified),
    onSuccess: refresh,
  });
  const exporter = useMutation({
    mutationFn: async (id: string) => download(`${id}.yaml`, await api.exportSearch(id)),
  });

  const list = searches.data ?? [];
  // A pinned search opens by its address (`#open=<id>`, D259), in a new tab too.
  const linked = targetIn(useSection(), "open");
  const opened = linked ?? seeded;
  // A pin opened while another search is open replaces it.
  useEffect(() => {
    if (linked) setRunning(null);
  }, [linked]);
  const missing = linked !== null && searches.isSuccess && !list.some((s) => s.id === linked);
  const running = !canRunSql
    ? null
    : (chosen ?? (opened ? (list.find((s) => s.id === opened) ?? null) : null));
  const error = [remove.error, importer.error, exporter.error, verifier.error].find(Boolean);

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        title="Saved searches"
        count={`${list.length} ${list.length === 1 ? "search" : "searches"}`}
        secondary={
          canAuthor ? [{ label: "Import YAML", onClick: () => file.current?.click() }] : []
        }
      />
      <input
        ref={file}
        type="file"
        accept=".yaml,.yml,application/yaml"
        aria-label="Import file"
        className="hidden"
        onChange={async (e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) importer.mutate(await f.text());
        }}
      />
      <div className="flex flex-col gap-3 px-5 py-3">
        {!canRunSql ? (
          <p role="note" className="text-sm text-text-secondary">
            {AUDITOR_SQL_OFF}
          </p>
        ) : null}
        {missing ? (
          <p role="status" className="text-sm text-text-secondary">
            That saved search is gone or no longer shared with you.
          </p>
        ) : null}
        {notice ? (
          <p role="status" className="text-sm text-text-secondary">
            {notice}
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error instanceof ApiError ? error.message : "Something went wrong."}
          </p>
        ) : null}
        {toDashboard ? (
          <AddToDashboardPanel
            key={toDashboard.id}
            search={toDashboard}
            onClose={() => setToDashboard(null)}
          />
        ) : null}
        {running ? (
          <SearchRunner
            key={running.id}
            search={running}
            onClose={() => {
              setRunning(null);
              setSeeded(null);
              if (linked) setFragment("", true);
            }}
          />
        ) : null}
        {canRunSql ? (
          <p className="text-sm text-text-muted">
            Start from a tested query in the{" "}
            <a
              href={pathFor("library")}
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                e.preventDefault();
                navigate("library");
              }}
              className="text-accent-text hover:underline"
            >
              Library
            </a>
          </p>
        ) : null}
        <section className="overflow-hidden rounded-card border border-border bg-surface">
          {list.length === 0 && !searches.isPending ? (
            <EmptyState
              kind="not-set-up"
              title="No saved searches yet"
              detail="Write a query on Logs and choose Save, or import a YAML file."
            />
          ) : (
            <table aria-label="Saved searches" className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-text-secondary">
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Tags</th>
                  <th className="px-3 py-2">Visibility</th>
                  <th className="px-3 py-2">Owner</th>
                  <th aria-label="Scheduled" className="px-3 py-2">
                    <span className="flex items-center gap-1.5">
                      Scheduled
                      <About
                        lead="About this"
                        text="Editing a search updates your own schedules of it at once (their next run notes the change). Other people's schedules of it pause until they review and resume."
                      />
                    </span>
                  </th>
                  <th className="px-3 py-2" aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {list.map((s) => {
                  const mine = s.owner_id === myId;
                  return (
                    <tr key={s.id} className="border-b border-border align-top last:border-0">
                      <td className="px-3 py-2.5">
                        <div className="font-semibold">{s.name}</div>
                        <div className="font-mono text-sm text-text-muted">{s.id}</div>
                        {s.origin?.ask_prompt ? (
                          // Informational only: the question the SQL was written from.
                          <div className="mt-0.5 max-w-[48ch] truncate text-sm text-text-secondary">
                            From Ask AI: {s.origin.ask_prompt}
                          </div>
                        ) : null}
                        {s.origin?.simple_text ? (
                          <div className="mt-0.5 max-w-[48ch] truncate font-mono text-sm text-text-secondary">
                            Simple search: {s.origin.simple_text}
                          </div>
                        ) : null}
                        {s.verified ? (
                          <span
                            title="An administrator verified this search; Ask uses it as an example. Editing it clears the mark."
                            className="mt-1 inline-block rounded-badge bg-local-bg px-2 py-px text-xs text-local-tx"
                          >
                            Verified
                          </span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="flex flex-wrap gap-1">
                          {s.tags.map((t) => (
                            <span
                              key={t}
                              className="rounded-badge bg-info-bg px-2 py-px text-xs text-info-tx"
                            >
                              {t}
                            </span>
                          ))}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 capitalize">{s.visibility}</td>
                      <td className="px-3 py-2.5 text-text-secondary">
                        {mine ? "You" : "Someone else"}
                      </td>
                      <td className="px-3 py-2.5">
                        <ScheduledCell
                          schedules={schedules.isSuccess ? (scheduledBy.get(s.id) ?? []) : null}
                          failed={schedules.isError}
                        />
                      </td>
                      <td className="whitespace-nowrap px-3 py-2.5 text-right">
                        {confirming === s.id ? (
                          <span className="flex items-center justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => remove.mutate(s.id)}
                              className="rounded border border-danger px-2 py-0.5 text-danger hover:bg-surface-head"
                            >
                              Delete
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirming(null)}
                              className="px-2 py-0.5 text-text-secondary"
                            >
                              Keep
                            </button>
                          </span>
                        ) : (
                          <span className="flex items-center justify-end gap-1">
                            <button
                              type="button"
                              aria-label={`Run ${s.name}`}
                              onClick={() => setRunning(s)}
                              disabled={!canRunSql}
                              title={canRunSql ? undefined : AUDITOR_SQL_OFF}
                              className="px-2 py-0.5 font-semibold text-accent-text disabled:text-text-muted"
                            >
                              Run
                            </button>
                            {mine && canAuthor ? (
                              <button
                                type="button"
                                aria-label={`Edit ${s.name}`}
                                onClick={() => {
                                  seedSearch({ savedId: s.id, sql: s.sql });
                                  navigate("logs");
                                }}
                                className="px-2 py-0.5 text-text-secondary hover:text-text"
                              >
                                Edit
                              </button>
                            ) : null}
                            {canAuthor ? (
                              <button
                                type="button"
                                aria-label={`Add ${s.name} to dashboard`}
                                onClick={() => setToDashboard(s)}
                                className="px-2 py-0.5 text-text-secondary hover:text-text"
                              >
                                Add to dashboard
                              </button>
                            ) : null}
                            {canAuthor ? (
                              <button
                                type="button"
                                aria-label={`Schedule ${s.name}`}
                                onClick={() => {
                                  seedSchedule({ kind: "search", targetId: s.id });
                                  navigate("schedules");
                                }}
                                className="px-2 py-0.5 text-text-secondary hover:text-text"
                              >
                                Schedule
                              </button>
                            ) : null}
                            <PinButton kind="search" id={s.id} name={s.name} />
                            <button
                              type="button"
                              aria-label={`Export ${s.name}`}
                              onClick={() => exporter.mutate(s.id)}
                              className="px-2 py-0.5 text-text-secondary hover:text-text"
                            >
                              Export
                            </button>
                            {isAdmin && (s.verified || s.visibility === "shared") ? (
                              <button
                                type="button"
                                aria-label={`${s.verified ? "Unverify" : "Verify"} ${s.name}`}
                                onClick={() => verifier.mutate(s)}
                                className="px-2 py-0.5 text-text-secondary hover:text-text"
                              >
                                {s.verified ? "Unverify" : "Verify"}
                              </button>
                            ) : null}
                            {mine || isAdmin ? (
                              <button
                                type="button"
                                aria-label={`Delete ${s.name}`}
                                onClick={() => setConfirming(s.id)}
                                className="px-2 py-0.5 text-text-secondary hover:text-text"
                              >
                                Delete
                              </button>
                            ) : null}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
        <p className="text-sm text-text-muted">
          Saved searches run with your own source access: a shared search never shows you more than
          you could search yourself.
        </p>
      </div>
    </div>
  );
}

/** The schedules that run one saved search, each a link to it on Alerts > Schedules. */
interface ScheduledCellProps {
  /** null until the schedules have loaded: "No" is only said once that is known. */
  schedules: Schedule[] | null;
  failed: boolean;
}

function ScheduledCell({ schedules, failed }: ScheduledCellProps) {
  if (failed) return <span className="text-text-secondary">Could not load</span>;
  if (!schedules) return <span className="sr-only">Loading</span>;
  if (schedules.length === 0) return <span className="text-text-muted">No</span>;
  return (
    <ul className="flex flex-col gap-0.5">
      {schedules.map((sch) => (
        <li key={sch.schedule_id}>
          <a
            href={`${pathFor("schedules")}#item=${sch.schedule_id}`}
            onClick={(e) => {
              if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
              e.preventDefault();
              navigate("schedules", `item=${sch.schedule_id}`);
            }}
            className="text-accent-text hover:underline"
          >
            {cronLabel(sch.cron)}
          </a>
          {sch.paused ? <span className="text-text-secondary"> (paused)</span> : null}
        </li>
      ))}
    </ul>
  );
}
