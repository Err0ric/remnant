import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Field } from "@/features/auth/Field";
import { FormError } from "@/features/auth/FormError";
import { ApiError, api, type Draft, type DraftSampleInput } from "@/lib/api";
import type { DraftSeed } from "./draftSeed";

const ID_PATTERN = /^[a-z][a-z0-9_]{1,63}$/;

interface NewDraftFormProps {
  allowedRoots: string[];
  onCreated: (draft: Draft) => void;
  onCancel: () => void;
  /** Values from Discover: the id, and a file sample for the candidate it came from. */
  seed?: DraftSeed | null;
}

export function NewDraftForm({
  allowedRoots,
  onCreated,
  onCancel,
  seed = null,
}: NewDraftFormProps) {
  const client = useQueryClient();
  const [id, setId] = useState(seed?.templateId ?? "");
  const [from, setFrom] = useState("");
  const [kind, setKind] = useState<DraftSampleInput["kind"]>(seed ? "file" : "pasted");
  const [path, setPath] = useState(seed?.path ?? allowedRoots[0] ?? "");
  const [glob, setGlob] = useState(seed?.glob ?? "*.log");
  const [text, setText] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const templates = useQuery({ queryKey: ["templates"], queryFn: api.templates });

  const create = useMutation({
    mutationFn: api.createDraft,
    onSuccess: async (draft) => {
      await client.invalidateQueries({ queryKey: ["drafts"] });
      onCreated(draft);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!ID_PATTERN.test(id)) {
      setLocalError(
        "Template ID: lowercase letters, digits, and underscores, starting with a letter.",
      );
      return;
    }
    setLocalError(null);
    const sample: DraftSampleInput =
      kind === "file" ? { kind, path, glob } : kind === "pasted" ? { kind, text } : { kind };
    create.mutate({ template_id: id, from_template: from || null, sample });
  };

  return (
    <form
      onSubmit={submit}
      aria-label="New template draft"
      className="rounded-card border border-border bg-surface p-4"
    >
      <h2 className="mb-3 text-base font-semibold">New template draft</h2>
      <div className="grid gap-4 md:grid-cols-2">
        <Field
          label="Template ID"
          help="Used by sources, e.g. hq_firewall. Starter template IDs are taken."
          value={id}
          onChange={(e) => setId(e.target.value.trim())}
          className="font-mono"
          required
        />
        <div className="flex flex-col gap-1">
          <label htmlFor="draft-from" className="text-sm font-semibold">
            Start from
          </label>
          <select
            id="draft-from"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            className="h-9 rounded border border-border-strong bg-inset px-2 text-sm text-text"
          >
            <option value="">Blank template (each line becomes a message)</option>
            {(templates.data ?? []).map((t) => (
              <option key={t.id} value={t.id}>
                Copy of {t.name}
              </option>
            ))}
          </select>
          <p className="text-sm text-text-muted">Copy the closest template and adjust it.</p>
        </div>
      </div>

      <fieldset className="mt-4">
        <legend className="text-sm font-semibold">Sample lines</legend>
        <div className="mt-1 flex flex-wrap gap-4 text-sm">
          {(
            [
              ["pasted", "Paste lines"],
              ["file", "File on this server"],
              ["none", "No sample yet"],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className="flex items-center gap-1.5">
              <input
                type="radio"
                name="sample-kind"
                checked={kind === value}
                onChange={() => setKind(value)}
              />
              {label}
            </label>
          ))}
        </div>
        {kind === "pasted" ? (
          <div className="mt-2 flex flex-col gap-1">
            <label htmlFor="draft-sample" className="sr-only">
              Pasted sample
            </label>
            <textarea
              id="draft-sample"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={8}
              spellCheck={false}
              className="rounded border border-border-strong bg-inset p-2 font-mono text-sm text-text"
            />
            <p className="text-sm text-text-muted">
              Up to 200 lines. Kept with the draft and deleted with it. Never sent to a cloud AI
              provider.
            </p>
          </div>
        ) : kind === "file" ? (
          <div className="mt-2 grid gap-4 md:grid-cols-2">
            <Field
              label="File or folder"
              help={
                allowedRoots.length
                  ? `Must be inside: ${allowedRoots.join(", ")}`
                  : "No folders are allowed yet. Set paths.allowed_roots on the server."
              }
              value={path}
              onChange={(e) => setPath(e.target.value)}
              className="font-mono"
            />
            <Field
              label="File pattern"
              help="For folders, e.g. *.log. ** is not allowed for samples."
              value={glob}
              onChange={(e) => setGlob(e.target.value)}
              className="font-mono"
            />
          </div>
        ) : null}
      </fieldset>

      <div className="mt-3">
        <FormError
          message={localError ?? (create.error instanceof ApiError ? create.error.message : null)}
        />
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          disabled={create.isPending}
          className="h-8 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {create.isPending ? "Creating" : "Create draft"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="h-8 rounded border border-border-strong px-4 text-sm text-text hover:bg-surface-head"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
