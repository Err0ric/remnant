import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { ClassificationBadge } from "./ClassificationBadge";

type Label = "local_only" | "cloud_allowed";

interface ClassificationEditorProps {
  sourceId: string;
  value: Label;
}

const HELP: Record<Label, string> = {
  local_only:
    "Cloud AI providers are refused for this source, including events already stored. Local models still work.",
  cloud_allowed:
    "New events from this source may be sent to cloud AI providers when someone uses Ask or Explain. Events already stored stay local only.",
};

/** Admins change a source's classification here; the change is audited (source.classify). */
export function ClassificationEditor({ sourceId, value }: ClassificationEditorProps) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<Label>(value);
  const save = useMutation({
    mutationFn: () => api.classifySource(sourceId, choice),
    onSuccess: () => {
      setOpen(false);
      void client.invalidateQueries({ queryKey: ["source-list"] });
      void client.invalidateQueries({ queryKey: ["sources"] });
    },
  });

  if (!open) {
    return (
      <span className="flex items-center gap-2">
        <ClassificationBadge value={value} />
        <button
          type="button"
          aria-label={`Change classification of ${sourceId}`}
          onClick={() => {
            setChoice(value);
            setOpen(true);
          }}
          className="text-sm text-accent-text hover:underline"
        >
          Change
        </button>
      </span>
    );
  }
  return (
    <fieldset className="flex max-w-[22rem] flex-col gap-1.5 whitespace-normal text-sm">
      <legend className="sr-only">Classification of {sourceId}</legend>
      {(["local_only", "cloud_allowed"] as const).map((v) => (
        <label key={v} className="flex items-start gap-2">
          <input
            type="radio"
            name={`classification-${sourceId}`}
            checked={choice === v}
            onChange={() => setChoice(v)}
            className="mt-1"
          />
          <span>
            <ClassificationBadge value={v} />
            <span className="mt-0.5 block text-text-secondary">{HELP[v]}</span>
          </span>
        </label>
      ))}
      {save.error ? (
        <span role="alert" className="text-danger">
          {save.error instanceof ApiError ? save.error.message : "Could not save"}
        </span>
      ) : null}
      <span className="flex gap-2">
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending || choice === value}
          className="h-7 rounded bg-accent px-3 font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="h-7 rounded border border-border-strong px-3 hover:bg-surface-head"
        >
          Cancel
        </button>
      </span>
    </fieldset>
  );
}
