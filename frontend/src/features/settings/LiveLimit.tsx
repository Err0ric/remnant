import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";

/** The live search time limit (ADR-0036 row 5): one setting for every role. */
export function LiveLimit({ canEdit }: { canEdit: boolean }) {
  const client = useQueryClient();
  const current = useQuery({ queryKey: ["live-limit"], queryFn: api.liveLimit });
  const [draft, setDraft] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (minutes: number) => api.setLiveLimit(minutes),
    onSuccess: (data) => {
      client.setQueryData(["live-limit"], data);
      setDraft(null);
    },
  });
  const value = draft ?? String(current.data?.minutes ?? "");
  const n = Number(value);
  const valid = Number.isInteger(n) && n >= 1 && n <= 1440;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (valid) save.mutate(n);
  };
  return (
    <section aria-label="Live search time limit" className="flex flex-col gap-1">
      <h2 className="text-base font-semibold">Live search time limit</h2>
      <p className="text-text-secondary">
        A live search stops after this long and offers Resume, so a forgotten tab does not keep a
        query running. Everyone has the same limit and at most 2 live searches at once.
      </p>
      {canEdit ? (
        <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
          <input
            aria-label="Minutes"
            inputMode="numeric"
            value={value}
            onChange={(e) => setDraft(e.target.value)}
            className="h-8 w-24 rounded border border-border-strong bg-surface px-2 tabular-nums"
          />
          <span className="text-text-secondary">minutes (1 to 1440)</span>
          <button
            type="submit"
            disabled={save.isPending || draft === null || !valid}
            className="h-8 rounded bg-accent px-3 font-semibold text-white disabled:opacity-50"
          >
            Save
          </button>
          {save.isError ? (
            <span role="alert" className="text-danger">
              {save.error instanceof ApiError ? save.error.message : "Could not save."}
            </span>
          ) : null}
        </form>
      ) : (
        <p>{current.data ? `${current.data.minutes} minutes` : ""}</p>
      )}
    </section>
  );
}
