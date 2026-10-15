import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Command, PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api } from "@/lib/api";
import { DraftEditor } from "./DraftEditor";
import { takeDraftSeed } from "./draftSeed";
import { NewDraftForm } from "./NewDraftForm";

/** Admin page: templates in use, and drafts on their way to approval (ADR-0005). */
export function TemplatesPage() {
  // Arriving from Discover's "Write a parser": open the form already filled in.
  const [seed] = useState(takeDraftSeed);
  const [creating, setCreating] = useState(seed !== null);
  const [open, setOpen] = useState<string | null>(null);
  const templates = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  const drafts = useQuery({ queryKey: ["drafts"], queryFn: api.drafts });
  const settings = useQuery({ queryKey: ["source-list", "settings"], queryFn: api.sourceSettings });
  const draft = useQuery({
    queryKey: ["draft", open],
    queryFn: () => api.draft(open ?? ""),
    enabled: open !== null,
    staleTime: Infinity, // the editor owns the text once loaded
  });

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        crumbs={["Home", "Settings", "Templates"]}
        title="Templates"
        meta={`${templates.data?.length ?? 0} available · ${drafts.data?.length ?? 0} drafts`}
        commands={
          <Command
            label="New draft"
            primary
            onClick={() => {
              setOpen(null);
              setCreating(true);
            }}
            disabled={creating}
          />
        }
      />
      <div className="flex min-w-0 flex-col gap-3 px-5 py-3">
        {creating ? (
          <NewDraftForm
            seed={seed}
            allowedRoots={settings.data?.allowed_roots ?? []}
            onCreated={(d) => {
              setCreating(false);
              setOpen(d.template_id);
            }}
            onCancel={() => setCreating(false)}
          />
        ) : null}

        {open && draft.data ? (
          <DraftEditor
            key={`${draft.data.template_id}:${draft.data.updated_at}`}
            draft={draft.data}
            onClosed={() => setOpen(null)}
          />
        ) : null}
        {open && draft.isError ? (
          <p role="alert" className="text-sm text-danger">
            {draft.error instanceof ApiError ? draft.error.message : "Could not load the draft."}
          </p>
        ) : null}

        <section className="overflow-hidden rounded-card border border-border bg-surface">
          <div className="border-b border-border bg-surface-head px-3 py-2">
            <h2 className="text-base font-semibold">Drafts</h2>
          </div>
          {(drafts.data ?? []).length === 0 ? (
            <p className="px-3 py-6 text-center text-sm text-text-secondary">
              No drafts. Start one from a copy of the closest template, or from a blank one.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-text-secondary">
                  <th className="px-3 py-2 font-semibold">Draft</th>
                  <th className="px-3 py-2 font-semibold">Sample</th>
                  <th className="px-3 py-2 font-semibold">Updated</th>
                  <th className="px-3 py-2" aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {(drafts.data ?? []).map((d) => (
                  <tr key={d.template_id} className="border-b border-border last:border-0">
                    <td className="px-3 py-2 font-mono">{d.template_id}</td>
                    <td className="px-3 py-2">
                      {d.sample.kind === "file"
                        ? "File"
                        : d.sample.kind === "pasted"
                          ? `${d.sample.lines} pasted lines`
                          : "None"}
                    </td>
                    <td className="px-3 py-2 font-mono">
                      {d.updated_at.slice(0, 19).replace("T", " ")} UTC
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        onClick={() => {
                          setCreating(false);
                          setOpen(d.template_id);
                        }}
                        aria-label={`Open draft ${d.template_id}`}
                        className="rounded border border-border-strong px-2 py-0.5 text-text hover:bg-surface-head"
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="overflow-hidden rounded-card border border-border bg-surface">
          <div className="border-b border-border bg-surface-head px-3 py-2">
            <h2 className="text-base font-semibold">Available templates</h2>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-secondary">
                <th className="px-3 py-2 font-semibold">Template</th>
                <th className="px-3 py-2 font-semibold">Version</th>
                <th className="px-3 py-2 font-semibold">Format</th>
              </tr>
            </thead>
            <tbody>
              {(templates.data ?? []).map((t) => (
                <tr key={t.id} className="border-b border-border last:border-0">
                  <td className="px-3 py-2">
                    <div>{t.name}</div>
                    <div className="font-mono text-text-muted">{t.id}</div>
                  </td>
                  <td className="px-3 py-2 font-mono">{t.version}</td>
                  <td className="px-3 py-2">
                    {t.payload_format}
                    {t.envelope === "syslog" ? " over syslog" : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}
