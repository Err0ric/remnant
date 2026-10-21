import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, type SourceFormat, type TemplateInfo } from "@/lib/api";
import { parserHelp, parserLabel } from "@/lib/parsers";
import { ParserSelect } from "./ParserSelect";

interface ParserEditorProps {
  sourceId: string;
  templateId: string | null | undefined;
  format: SourceFormat;
  templates: TemplateInfo[];
  canManage: boolean;
}

/** A source's parser, changeable by admins (ADR-0012, audited as source.parser_change). */
export function ParserEditor({
  sourceId,
  templateId,
  format,
  templates,
  canManage,
}: ParserEditorProps) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<string | null>(templateId ?? null);
  const save = useMutation({
    mutationFn: () => api.setSourceParser(sourceId, choice),
    onSuccess: () => {
      setOpen(false);
      void client.invalidateQueries({ queryKey: ["source-list"] });
    },
  });
  const label = parserLabel(templateId, format, templates);

  if (!open) {
    return (
      <span className="flex flex-wrap items-center gap-x-2 text-sm text-text-secondary">
        <span>{label}</span>
        {canManage ? (
          <button
            type="button"
            aria-label={`Change parser of ${sourceId}`}
            onClick={() => {
              setChoice(templateId ?? null);
              setOpen(true);
            }}
            className="text-accent-text hover:underline"
          >
            Change
          </button>
        ) : null}
      </span>
    );
  }
  return (
    <fieldset className="mt-1 flex max-w-[24rem] flex-col gap-1.5 whitespace-normal text-sm">
      <legend className="sr-only">Parser of {sourceId}</legend>
      <ParserSelect
        id={`parser-${sourceId}`}
        label={`Parser for ${sourceId}`}
        templateId={choice}
        format={format}
        templates={templates}
        formats={[format]}
        onChange={(next) => setChoice(next)}
      />
      <span className="text-text-secondary">{parserHelp(choice, templates)}</span>
      <span className="text-text-muted">
        Only lines read from now on use the new parser. Events already stored keep theirs.
      </span>
      {save.error ? (
        <span role="alert" className="text-danger">
          {save.error instanceof ApiError ? save.error.message : "Could not save"}
        </span>
      ) : null}
      <span className="flex gap-2">
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending || choice === (templateId ?? null)}
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
