import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";

/** The optional install name in the top bar (ADR-0038 nav pass 2). Shown to signed-in
 * people only; admins set it here. */
export function InstallName({ canEdit }: { canEdit: boolean }) {
  const client = useQueryClient();
  const current = useQuery({ queryKey: ["install"], queryFn: api.install });
  const [draft, setDraft] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (name: string) => api.setInstall(name),
    onSuccess: (data) => {
      client.setQueryData(["install"], data);
      setDraft(null);
    },
  });
  const value = draft ?? current.data?.name ?? "";
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(value);
  };
  return (
    <section aria-label="Install name" className="flex flex-col gap-1">
      <h2 className="text-base font-semibold">Install name</h2>
      <p className="text-text-secondary">
        Shown in the top bar to people who are signed in, never on the sign-in page. Leave it empty
        to show nothing.
      </p>
      {canEdit ? (
        <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
          <input
            aria-label="Install name"
            value={value}
            maxLength={40}
            placeholder="For example: Example SOC"
            onChange={(e) => setDraft(e.target.value)}
            className="h-8 w-64 rounded border border-border-strong bg-surface px-2"
          />
          <button
            type="submit"
            disabled={save.isPending || draft === null}
            className="h-8 rounded bg-accent px-3 font-semibold text-white disabled:opacity-50"
          >
            Save
          </button>
          {save.isError ? (
            <span role="alert" className="text-danger">
              {save.error instanceof ApiError
                ? "Use letters, digits, spaces, and . , & ( ) ' / - only, up to 40 characters."
                : "Could not save."}
            </span>
          ) : null}
        </form>
      ) : (
        <p>{current.data?.name || "Not set"}</p>
      )}
    </section>
  );
}
