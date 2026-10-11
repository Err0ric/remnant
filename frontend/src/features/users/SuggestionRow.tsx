import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { FormError } from "@/features/auth/FormError";
import { ApiError, api, type GroupSuggestion } from "@/lib/api";

interface SuggestionRowProps {
  suggestion: GroupSuggestion;
}

/** One suggested group: tick sources, then create or extend the group. */
export function SuggestionRow({ suggestion }: SuggestionRowProps) {
  const client = useQueryClient();
  const [ticked, setTicked] = useState<string[]>(suggestion.missing);
  const apply = useMutation({
    mutationFn: () =>
      api.acceptGroupSuggestion({
        kind: suggestion.kind,
        key: suggestion.key,
        source_ids: ticked,
      }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["groups"] });
      await client.invalidateQueries({ queryKey: ["group-suggestions"] });
    },
  });
  const toggle = (id: string) =>
    setTicked((t) => (t.includes(id) ? t.filter((x) => x !== id) : [...t, id]));
  const label = suggestion.group_id ? `Add to ${suggestion.name}` : `Create ${suggestion.name}`;
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
      <span className="min-w-40 font-semibold">
        {suggestion.name}{" "}
        <span className="font-normal text-text-muted">
          ({suggestion.kind === "category" ? "category" : "vendor"})
        </span>
      </span>
      {suggestion.missing.map((id) => (
        <label key={id} className="flex items-center gap-1.5 font-mono">
          <input type="checkbox" checked={ticked.includes(id)} onChange={() => toggle(id)} />
          {id}
        </label>
      ))}
      <button
        type="button"
        onClick={() => apply.mutate()}
        disabled={!ticked.length || apply.isPending}
        className="ml-auto h-7 rounded border border-border-strong px-3 hover:bg-surface-head disabled:opacity-40"
      >
        {label}
      </button>
      <FormError message={apply.error instanceof ApiError ? apply.error.message : null} />
    </li>
  );
}
