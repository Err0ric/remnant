import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Command, PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api, type ProviderConfig, type ProviderHealth } from "@/lib/api";
import { LocalityBadge } from "./LocalityBadge";
import { ModelCell } from "./ModelCell";
import { ProviderForm } from "./ProviderForm";

/** AI providers (SPEC 6.1). Admin only; locality is computed by the server from the URL. */
export function ProvidersPage() {
  const client = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [health, setHealth] = useState<Record<string, ProviderHealth>>({});
  const providers = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const list = providers.data ?? [];

  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ["providers"] });
    await client.invalidateQueries({ queryKey: ["ask-providers"] });
  };
  const toggle = useMutation({
    mutationFn: (p: ProviderConfig) => api.updateProvider(p.provider_id, { enabled: !p.enabled }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteProvider(id),
    onSuccess: async () => {
      setConfirmDelete(null);
      await refresh();
    },
  });
  const choose = useMutation({
    mutationFn: ({ id, model }: { id: string; model: string }) => api.updateProvider(id, { model }),
    onSuccess: refresh,
  });
  const test = useMutation({
    mutationFn: (id: string) => api.testProvider(id),
    onSuccess: (h, id) => setHealth((prev) => ({ ...prev, [id]: h })),
  });

  const failure = [toggle.error, remove.error, test.error, choose.error].find(Boolean);

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        crumbs={["Home", "Settings", "AI providers"]}
        title="AI providers"
        meta={`${list.length} ${list.length === 1 ? "provider" : "providers"}`}
        commands={
          <Command
            label="Add provider"
            primary
            onClick={() => {
              setEditing(null);
              setAdding(true);
            }}
            disabled={adding}
          />
        }
      />
      <div className="flex flex-col gap-3 px-5 py-3">
        <p className="max-w-3xl text-sm text-text-secondary">
          Models write SQL and explain results; they never read every event. Local providers can see
          any source. Cloud providers only ever receive data from sources marked cloud allowed, and
          every call is recorded in the audit log.
        </p>
        {adding ? (
          <ProviderForm onDone={() => setAdding(false)} onCancel={() => setAdding(false)} />
        ) : null}
        {failure ? (
          <p role="alert" className="text-sm text-danger">
            {failure instanceof ApiError ? failure.message : "That did not work"}
          </p>
        ) : null}
        <section className="overflow-hidden rounded-card border border-border bg-surface">
          <div className="overflow-x-auto">
            <table aria-label="AI providers" className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
                  <th className="px-3 py-2 font-semibold">Name</th>
                  <th className="px-3 py-2 font-semibold">Where</th>
                  <th className="px-3 py-2 font-semibold">Model</th>
                  <th className="px-3 py-2 font-semibold">Key</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2" aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {list.map((p) => {
                  const h = health[p.provider_id];
                  return (
                    <tr
                      key={p.provider_id}
                      className="border-b border-border align-top last:border-0"
                    >
                      <td className="px-3 py-2">
                        <div className="font-semibold">{p.name}</div>
                        <div className="font-mono text-text-muted">{p.base_url}</div>
                      </td>
                      <td className="px-3 py-2">
                        <LocalityBadge locality={p.locality} hostFound={p.host_found} />
                      </td>
                      <td className="px-3 py-2">
                        <ModelCell
                          providerName={p.name}
                          model={p.model}
                          models={h?.ok ? h.models : []}
                          saving={choose.isPending}
                          onChoose={(model) => choose.mutate({ id: p.provider_id, model })}
                        />
                      </td>
                      <td className="px-3 py-2">{p.has_api_key ? "Saved" : "None"}</td>
                      <td className="px-3 py-2">
                        {p.enabled ? "Enabled" : "Disabled"}
                        {h ? (
                          <div className={h.ok ? "text-ok" : "text-danger"} role="status">
                            {h.detail}
                          </div>
                        ) : null}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-right">
                        <button
                          type="button"
                          className="rounded px-2 py-1 hover:bg-surface-head"
                          onClick={() => test.mutate(p.provider_id)}
                          aria-label={`Test ${p.name}`}
                        >
                          Test
                        </button>
                        <button
                          type="button"
                          className="rounded px-2 py-1 hover:bg-surface-head"
                          onClick={() => {
                            setAdding(false);
                            setEditing(p.provider_id);
                          }}
                          aria-label={`Edit ${p.name}`}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="rounded px-2 py-1 hover:bg-surface-head disabled:opacity-40"
                          onClick={() => toggle.mutate(p)}
                          disabled={!p.enabled && !p.model}
                          title={!p.enabled && !p.model ? "Choose a model first" : undefined}
                          aria-label={`${p.enabled ? "Disable" : "Enable"} ${p.name}`}
                        >
                          {p.enabled ? "Disable" : "Enable"}
                        </button>
                        {confirmDelete === p.provider_id ? (
                          <>
                            <button
                              type="button"
                              className="rounded px-2 py-1 font-semibold text-danger hover:bg-surface-head"
                              onClick={() => remove.mutate(p.provider_id)}
                            >
                              Confirm delete
                            </button>
                            <button
                              type="button"
                              className="rounded px-2 py-1 hover:bg-surface-head"
                              onClick={() => setConfirmDelete(null)}
                            >
                              Keep
                            </button>
                          </>
                        ) : (
                          <button
                            type="button"
                            className="rounded px-2 py-1 hover:bg-surface-head"
                            onClick={() => setConfirmDelete(p.provider_id)}
                            aria-label={`Delete ${p.name}`}
                          >
                            Delete
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {list.length === 0 && providers.isSuccess ? (
            <p className="px-3 py-8 text-center text-sm text-text-secondary">
              No providers. Add a local one, such as Ollama, to use Ask.
            </p>
          ) : null}
        </section>
        {editing
          ? (() => {
              const p = list.find((x) => x.provider_id === editing);
              return p ? (
                <ProviderForm
                  key={p.provider_id}
                  existing={p}
                  models={health[p.provider_id]?.models ?? []}
                  onDone={() => setEditing(null)}
                  onCancel={() => setEditing(null)}
                />
              ) : null;
            })()
          : null}
      </div>
    </div>
  );
}
