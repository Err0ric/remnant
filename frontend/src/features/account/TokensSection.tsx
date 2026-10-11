import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Field } from "@/features/auth/Field";
import { FormError } from "@/features/auth/FormError";
import { ApiError, api } from "@/lib/api";

function when(v: string | null): string {
  return v ? `${v.slice(0, 16).replace("T", " ")} UTC` : "Never";
}

/** Your CLI and API tokens: create (shown once), list, revoke. */
export function TokensSection() {
  const client = useQueryClient();
  const tokens = useQuery({ queryKey: ["tokens"], queryFn: api.tokens });
  const [label, setLabel] = useState("");
  const [days, setDays] = useState(90);
  const [secret, setSecret] = useState<string | null>(null);
  const refresh = () => client.invalidateQueries({ queryKey: ["tokens"] });
  const create = useMutation({
    mutationFn: api.createToken,
    onSuccess: async (t) => {
      setSecret(t.token);
      setLabel("");
      await refresh();
    },
  });
  const revoke = useMutation({ mutationFn: api.revokeToken, onSuccess: refresh });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (label.trim()) create.mutate({ label: label.trim(), days });
  };
  const list = tokens.data ?? [];

  return (
    <section className="overflow-hidden rounded-card border border-border bg-surface">
      <div className="border-b border-border bg-surface-head px-3 py-2">
        <h2 className="text-base font-semibold">CLI and API tokens</h2>
        <p className="text-sm text-text-muted">
          Each token acts as you, with your source access. Revoke any you no longer use.
        </p>
      </div>
      <div className="flex flex-col gap-3 p-3">
        {secret ? (
          <div role="status" className="rounded-card border border-accent bg-accent-subtle p-3">
            <p className="text-sm">
              Copy this token now. It is not shown again. Store it like a password.
            </p>
            <input
              readOnly
              aria-label="New token"
              value={secret}
              onFocus={(e) => e.currentTarget.select()}
              className="mt-2 h-8 w-full rounded border border-border-strong bg-inset px-2 font-mono text-sm"
            />
            <button
              type="button"
              onClick={() => setSecret(null)}
              className="mt-2 text-sm font-semibold text-accent-text"
            >
              Done
            </button>
          </div>
        ) : null}

        <form
          aria-label="Create token"
          onSubmit={submit}
          className="grid gap-3 md:grid-cols-[1fr_160px_auto] md:items-end"
        >
          <Field
            label="Name"
            help="What uses it, for example: nightly export script"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <Field
            label="Expires after (days)"
            type="number"
            min={1}
            max={365}
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          />
          <button
            type="submit"
            disabled={!label.trim() || create.isPending}
            className="mb-[22px] h-9 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
          >
            Create token
          </button>
        </form>
        <FormError message={create.error instanceof ApiError ? create.error.message : null} />

        {list.length === 0 && !tokens.isPending ? (
          <p className="text-sm text-text-secondary">
            No tokens. Signing in with <span className="font-mono">remnant login</span> creates one
            named after your computer.
          </p>
        ) : (
          <table aria-label="Tokens" className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-secondary">
                <th className="py-2 pr-3 font-semibold">Name</th>
                <th className="py-2 pr-3 font-semibold">Created</th>
                <th className="py-2 pr-3 font-semibold">Last used</th>
                <th className="py-2 pr-3 font-semibold">Expires</th>
                <th className="py-2" aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {list.map((t) => (
                <tr key={t.token_id} className="border-b border-border last:border-0">
                  <td className="py-2 pr-3">{t.label}</td>
                  <td className="py-2 pr-3 font-mono">{when(t.created_at)}</td>
                  <td className="py-2 pr-3 font-mono">{when(t.last_used_at)}</td>
                  <td className="py-2 pr-3 font-mono">{when(t.expires_at)}</td>
                  <td className="py-2 text-right">
                    <button
                      type="button"
                      aria-label={`Revoke ${t.label}`}
                      onClick={() => revoke.mutate(t.token_id)}
                      className="text-text-secondary hover:text-danger"
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
