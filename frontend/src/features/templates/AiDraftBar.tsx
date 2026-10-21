import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { FormError } from "@/features/auth/FormError";
import { ApiError, api, type Draft } from "@/lib/api";

interface AiDraftBarProps {
  templateId: string;
  /** True when the editor holds edits that a model draft would replace. */
  dirty: boolean;
  hasSample: boolean;
  onDrafted: (draft: Draft) => void;
}

/**
 * Optional: ask a configured model for the payload, transforms, mapping, and tests.
 * The result replaces the draft text and still has to pass preview and approval.
 */
export function AiDraftBar({ templateId, dirty, hasSample, onDrafted }: AiDraftBarProps) {
  const providers = useQuery({ queryKey: ["ask-providers"], queryFn: api.askProviders });
  const [chosen, setChosen] = useState("");
  const [confirm, setConfirm] = useState(false);
  const list = providers.data ?? [];
  const providerId = chosen || list[0]?.provider_id || "";
  const selected = list.find((p) => p.provider_id === providerId);
  const run = useMutation({
    mutationFn: () => api.aiDraft(templateId, providerId),
    onSuccess: (d) => {
      setConfirm(false);
      onDrafted(d);
    },
  });

  if (list.length === 0) {
    return (
      <p className="text-sm text-text-secondary">
        No AI provider is enabled. Write the template by hand, or enable one under AI providers.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-2 rounded-card border border-border bg-surface p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor="ai-provider" className="font-semibold">
          Draft with
        </label>
        <select
          id="ai-provider"
          value={providerId}
          onChange={(e) => setChosen(e.target.value)}
          className="h-8 rounded border border-border-strong bg-inset px-2 text-sm text-text"
        >
          {list.map((p) => (
            <option key={p.provider_id} value={p.provider_id}>
              {p.name} ({p.locality === "cloud" ? "cloud" : "local"})
            </option>
          ))}
        </select>
        {confirm ? (
          <>
            <span className="text-text-secondary">Replace your unsaved edits?</span>
            <button
              type="button"
              onClick={() => run.mutate()}
              className="h-8 rounded border border-border-strong px-3 text-text hover:bg-surface-head"
            >
              Replace
            </button>
            <button
              type="button"
              onClick={() => setConfirm(false)}
              className="px-2 text-text-secondary"
            >
              Keep edits
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => (dirty ? setConfirm(true) : run.mutate())}
            disabled={!hasSample || run.isPending}
            title={hasSample ? undefined : "Add sample lines to the draft first"}
            className="h-8 rounded border border-border-strong px-3 text-text hover:bg-surface-head disabled:opacity-60"
          >
            {run.isPending ? "Drafting" : "Draft parser"}
          </button>
        )}
      </div>
      <p className="text-sm text-text-muted">
        The model sees up to 20 sample lines and the column list, and writes only the payload,
        mappings, and tests. Pasted samples are never sent to a cloud provider
        {selected?.locality === "cloud" ? "; this one is a cloud provider" : ""}.
      </p>
      <FormError message={run.error instanceof ApiError ? run.error.message : null} />
    </div>
  );
}
