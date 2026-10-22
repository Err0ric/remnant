import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Command, PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api, type SavedSearch, type User } from "@/lib/api";
import { navigate } from "@/lib/route";
import { seedSchedule } from "@/lib/scheduleSeed";
import { seedSearch } from "@/lib/searchSeed";
import { takeSavedSeed } from "@/lib/savedSeed";
import { AddToDashboardPanel } from "@/features/dashboard/AddToDashboard";
import { SearchRunner } from "./SearchRunner";

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
  const running = chosen ?? (seeded ? (list.find((s) => s.id === seeded) ?? null) : null);
  const error = [remove.error, importer.error, exporter.error, verifier.error].find(Boolean);

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        crumbs={["Home", "Investigate", "Saved searches"]}
        title="Saved searches"
        meta={`${list.length} ${list.length === 1 ? "search" : "searches"}`}
        commands={
          canAuthor ? (
            <Command label="Import YAML" onClick={() => file.current?.click()} />
          ) : undefined
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
            }}
          />
        ) : null}
        <section className="overflow-hidden rounded-card border border-border bg-surface">
          {list.length === 0 && !searches.isPending ? (
            <div className="px-3 py-8 text-center">
              <p className="font-semibold">No saved searches yet</p>
              <p className="mt-1 text-sm text-text-secondary">
                Write a query on Search and choose Save, or import a YAML file.
              </p>
            </div>
          ) : (
            <table aria-label="Saved searches" className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
                  <th className="px-3 py-2 font-semibold">Name</th>
                  <th className="px-3 py-2 font-semibold">Tags</th>
                  <th className="px-3 py-2 font-semibold">Visibility</th>
                  <th className="px-3 py-2 font-semibold">Owner</th>
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
                            From Ask: {s.origin.ask_prompt}
                          </div>
                        ) : null}
                        {s.origin?.simple_text ? (
                          <div className="mt-0.5 max-w-[48ch] truncate font-mono text-sm text-text-secondary">
                            Simple search: {s.origin.simple_text}
                          </div>
                        ) : null}
                        {s.verified ? (
                          <span
                            title="An administrator verified this search; Ask uses it as an example"
                            className="mt-1 inline-block rounded-badge bg-local-bg px-2 py-px text-xs text-local-text"
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
                              className="rounded-badge bg-sev-info-bg px-2 py-px text-xs text-sev-info-text"
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
                      <td className="whitespace-nowrap px-3 py-2.5 text-right">
                        {confirming === s.id ? (
                          <span className="flex items-center justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => remove.mutate(s.id)}
                              className="rounded border border-danger px-2 py-0.5 text-danger hover:bg-sev-critical-bg"
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
                              className="px-2 py-0.5 font-semibold text-accent-text"
                            >
                              Run
                            </button>
                            {mine && canAuthor ? (
                              <button
                                type="button"
                                aria-label={`Edit ${s.name}`}
                                onClick={() => {
                                  seedSearch({ savedId: s.id, sql: s.sql });
                                  navigate("search");
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
          Saved searches always run with your own source access. A shared search never shows you
          more than you could search yourself. Verified searches are examples Ask learns from;
          editing one clears the mark. Editing a search updates your own schedules of it at once
          (their next run notes the change); other people's schedules of it pause until they review
          and resume.
        </p>
      </div>
    </div>
  );
}
