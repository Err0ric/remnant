import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { FormError } from "@/features/auth/FormError";
import { ApiError, api, type Draft, type DraftPreview, type TemplateApproval } from "@/lib/api";
import { AiDraftBar } from "./AiDraftBar";
import { PreviewPanel } from "./PreviewPanel";
import { YamlEditor } from "./YamlEditor";

interface DraftEditorProps {
  draft: Draft;
  onClosed: () => void;
}

function sampleLabel(d: Draft): string {
  if (d.sample.kind === "file") return `${d.sample.path ?? ""} · ${d.sample.glob ?? "*"}`;
  if (d.sample.kind === "pasted") return `${d.sample.lines} pasted lines`;
  return "No sample";
}

/**
 * Edit, preview, and approve one draft. Approve stays off until the saved YAML has
 * previewed clean, so what gets approved is exactly what was checked.
 */
export function DraftEditor({ draft, onClosed }: DraftEditorProps) {
  const client = useQueryClient();
  const [text, setText] = useState(draft.yaml);
  const [saved, setSaved] = useState(draft.yaml);
  const [preview, setPreview] = useState<{ yaml: string; result: DraftPreview } | null>(null);
  const [approved, setApproved] = useState<TemplateApproval | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [drafted, setDrafted] = useState(draft.llm_call_id !== null);
  const id = draft.template_id;
  const dirty = text !== saved;

  const save = useMutation({
    mutationFn: () => api.updateDraft(id, { yaml: text }),
    onSuccess: async (d) => {
      setSaved(d.yaml);
      await client.invalidateQueries({ queryKey: ["drafts"] });
    },
  });
  const check = useMutation({
    mutationFn: (yaml: string) => api.previewDraft(id, yaml),
    onSuccess: (result, yaml) => setPreview({ yaml, result }),
  });
  const approve = useMutation({
    // Names the reviewed bytes: if anyone saved since, the server refuses (409).
    mutationFn: (sha256: string) => api.approveDraft(id, sha256),
    onSuccess: async (a) => {
      setApproved(a);
      await client.invalidateQueries({ queryKey: ["drafts"] });
      await client.invalidateQueries({ queryKey: ["templates"] });
    },
  });
  const remove = useMutation({
    mutationFn: () => api.deleteDraft(id),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["drafts"] });
      onClosed();
    },
  });

  const canApprove =
    !dirty && preview !== null && preview.yaml === saved && preview.result.approvable;
  const error = [save.error, check.error, approve.error, remove.error].find(
    (e) => e instanceof ApiError,
  );

  if (approved) {
    return (
      <section aria-label="Approved" className="rounded-card border border-border bg-surface p-4">
        <h2 className="text-base font-semibold">
          Approved <span className="font-mono">{approved.template_id}</span> {approved.version}
        </h2>
        <p className="mt-1 text-sm text-text-secondary">
          Sources can use it now. Approval recorded with SHA-256{" "}
          <span className="font-mono">{approved.sha256.slice(0, 16)}</span>.
        </p>
        <button
          type="button"
          onClick={onClosed}
          className="mt-3 h-8 rounded border border-border-strong px-4 text-sm text-text hover:bg-surface-head"
        >
          Back to drafts
        </button>
      </section>
    );
  }

  return (
    <section aria-label={`Draft ${id}`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="font-mono text-base font-semibold">{id}</h2>
        <span className="text-sm text-text-secondary">Sample: {sampleLabel(draft)}</span>
        {draft.replaces_version ? (
          <span className="text-sm text-text-secondary">
            Replaces approved version {draft.replaces_version}; raise the version to approve.
          </span>
        ) : null}
      </div>
      <AiDraftBar
        templateId={id}
        dirty={dirty}
        hasSample={draft.sample.kind !== "none"}
        onDrafted={(d) => {
          setText(d.yaml);
          setSaved(d.yaml);
          setPreview(null);
          setDrafted(true);
          void client.invalidateQueries({ queryKey: ["drafts"] });
        }}
      />
      {drafted ? (
        <p className="text-sm text-text-secondary">
          Drafted by a model. Check the patterns, mappings, and tests before approving; the approval
          records which model call wrote it.
        </p>
      ) : null}
      <div className="grid min-w-0 gap-4 xl:grid-cols-2">
        <div className="min-w-0">
          <YamlEditor value={text} onChange={setText} label="Template YAML" />
        </div>
        <div className="min-w-0">
          {preview ? (
            <>
              {preview.yaml !== text ? (
                <p className="mb-2 text-sm text-text-secondary">
                  The YAML changed since this preview. Preview again.
                </p>
              ) : null}
              <PreviewPanel preview={preview.result} />
            </>
          ) : (
            <p className="text-sm text-text-secondary">
              Preview checks the template, runs its tests, and parses the sample. Nothing is saved
              or applied.
            </p>
          )}
        </div>
      </div>
      <FormError message={error instanceof ApiError ? error.message : null} />
      <div className="sticky bottom-0 flex flex-wrap items-center gap-2 border-t border-border bg-bg py-2">
        <button
          type="button"
          onClick={() => check.mutate(text)}
          disabled={check.isPending}
          className="h-8 rounded border border-border-strong px-4 text-sm text-text hover:bg-surface-head disabled:opacity-60"
        >
          {check.isPending ? "Checking" : "Preview"}
        </button>
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={!dirty || save.isPending}
          className="h-8 rounded border border-border-strong px-4 text-sm text-text hover:bg-surface-head disabled:opacity-60"
        >
          {save.isPending ? "Saving" : dirty ? "Save" : "Saved"}
        </button>
        <button
          type="button"
          onClick={() => preview && approve.mutate(preview.result.sha256)}
          disabled={!canApprove || approve.isPending}
          title={canApprove ? undefined : "Save, then preview with no problems, to approve"}
          className="h-8 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {approve.isPending ? "Approving" : "Approve"}
        </button>
        <span className="ml-auto flex items-center gap-2">
          {confirmDelete ? (
            <>
              <button
                type="button"
                onClick={() => remove.mutate()}
                className="rounded border border-danger px-2 py-0.5 text-sm text-danger"
              >
                Delete draft
              </button>
              <button
                type="button"
                onClick={() => setConfirmDelete(false)}
                className="px-2 py-0.5 text-sm text-text-secondary"
              >
                Keep
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="px-2 py-0.5 text-sm text-text-secondary hover:text-text"
            >
              Delete
            </button>
          )}
          <button
            type="button"
            onClick={onClosed}
            className="px-2 py-0.5 text-sm text-text-secondary hover:text-text"
          >
            Close
          </button>
        </span>
      </div>
    </section>
  );
}
