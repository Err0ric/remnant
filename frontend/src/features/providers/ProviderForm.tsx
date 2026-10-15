import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { OptionalSection } from "@/components/forms/OptionalSection";
import { Field } from "@/features/auth/Field";
import { FormError } from "@/features/auth/FormError";
import { ApiError, api, type ProviderConfig, type ProviderInput } from "@/lib/api";

interface ProviderFormProps {
  /** Edit this provider; omit to add a new one. */
  existing?: ProviderConfig;
  models?: string[];
  onDone: () => void;
  onCancel: () => void;
}

/**
 * Add or edit a model provider. A cloud URL needs an explicit acknowledgment, which the
 * server asks for (409 cloud_ack_required); the key is write-only and never shown again.
 */
const THINKING: Record<string, string> = {
  default: "model default",
  none: "off",
  low: "low",
  medium: "medium",
  high: "high",
};

export function ProviderForm({ existing, models = [], onDone, onCancel }: ProviderFormProps) {
  const client = useQueryClient();
  const [kind, setKind] = useState<"openai_compat" | "anthropic">(
    existing?.kind === "anthropic" ? "anthropic" : "openai_compat",
  );
  const [name, setName] = useState(existing?.name ?? "");
  const [baseUrl, setBaseUrl] = useState(existing?.base_url ?? "");
  const [model, setModel] = useState(existing?.model ?? "");
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [redact, setRedact] = useState(existing?.redact ?? false);
  const [reasoning, setReasoning] = useState<string>(existing?.reasoning ?? "default");
  const [needsAck, setNeedsAck] = useState(false);
  const [ack, setAck] = useState(false);

  const save = useMutation({
    mutationFn: (body: ProviderInput) =>
      existing ? api.updateProvider(existing.provider_id, body) : api.addProvider(body),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["providers"] });
      await client.invalidateQueries({ queryKey: ["ask-providers"] });
      onDone();
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === "cloud_ack_required") setNeedsAck(true);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body: ProviderInput = { name: name.trim(), model: model.trim() };
    if (!existing) body.kind = kind;
    if (!existing || baseUrl !== existing.base_url) body.base_url = baseUrl.trim();
    if (apiKey) body.api_key = apiKey;
    if (existing && clearKey) body.clear_api_key = true;
    if (existing && redact !== existing.redact) body.redact = redact;
    if (existing && reasoning !== (existing.reasoning ?? "default"))
      body.reasoning = reasoning as ProviderInput["reasoning"];
    if (ack) body.acknowledge_cloud = true;
    save.mutate(body);
  };

  const error =
    save.error instanceof ApiError && save.error.code !== "cloud_ack_required"
      ? save.error.message
      : save.isError && !(save.error instanceof ApiError)
        ? "Could not save the provider"
        : null;
  const listId = `models-${existing?.provider_id ?? "new"}`;

  return (
    <form
      aria-label={existing ? `Edit ${existing.name}` : "Add provider"}
      onSubmit={submit}
      className="rounded-card border border-border bg-surface p-4"
    >
      <h2 className="mb-3 text-base font-semibold">
        {existing ? `Edit ${existing.name}` : "Add provider"}
      </h2>
      <div className="grid gap-4 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm md:col-span-2">
          <span className="text-text-secondary">API</span>
          <select
            value={kind}
            disabled={Boolean(existing)}
            onChange={(e) => {
              const next = e.target.value as "openai_compat" | "anthropic";
              setKind(next);
              if (next === "anthropic" && !baseUrl) setBaseUrl("https://api.anthropic.com/v1");
              setNeedsAck(false);
              setAck(false);
            }}
            className="h-8 max-w-sm rounded border border-border-strong bg-surface px-2 text-sm disabled:opacity-60"
          >
            <option value="openai_compat">
              OpenAI-compatible (Ollama, LM Studio, vLLM, OpenAI, others)
            </option>
            <option value="anthropic">Anthropic Messages API (always cloud)</option>
          </select>
          {kind === "anthropic" ? (
            <span className="text-text-muted">
              Always treated as a cloud provider: data from local-only sources is never sent to it.
            </span>
          ) : null}
        </label>
        <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} required />
        <Field
          label="Base URL"
          help={
            kind === "anthropic"
              ? "Messages API root, normally https://api.anthropic.com/v1"
              : "OpenAI-compatible API root, for example http://ollama:11434/v1 or https://api.openai.com/v1"
          }
          value={baseUrl}
          onChange={(e) => {
            setBaseUrl(e.target.value);
            setNeedsAck(false);
            setAck(false);
          }}
          required
          className="font-mono"
        />
        <Field
          label="Model"
          help={
            models.length
              ? "Pick from the server's list or type a name"
              : "Test the provider to list its models"
          }
          value={model}
          onChange={(e) => setModel(e.target.value)}
          list={models.length ? listId : undefined}
          className="font-mono"
        />
        <Field
          label="API key"
          type="password"
          autoComplete="off"
          help={
            existing?.has_api_key
              ? "A key is saved. Leave blank to keep it."
              : "Optional for local servers. Stored encrypted; never shown again."
          }
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
      </div>
      {models.length ? (
        <datalist id={listId}>
          {models.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      ) : null}
      {existing?.has_api_key ? (
        <label className="mt-3 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={clearKey}
            onChange={(e) => setClearKey(e.target.checked)}
          />
          Remove the saved key
        </label>
      ) : null}
      {existing && (existing.kind !== "anthropic" || existing.locality === "cloud") ? (
        <div className="mt-3">
          <OptionalSection
            title="Answer behavior"
            summary={[
              existing.kind !== "anthropic"
                ? `Thinking: ${THINKING[reasoning] ?? reasoning}`
                : null,
              existing.locality === "cloud"
                ? `Tokens for names and addresses: ${redact ? "on" : "off"}`
                : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          >
            {existing && existing.kind !== "anthropic" ? (
              <label className="flex flex-col gap-1 text-sm md:col-span-2">
                <span className="font-semibold">Thinking</span>
                <select
                  value={reasoning}
                  onChange={(e) => setReasoning(e.target.value)}
                  className="h-8 max-w-xs rounded border border-border-strong bg-surface px-2 text-sm"
                >
                  <option value="default">Model default</option>
                  <option value="none">Off</option>
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
                <span className="text-text-muted">
                  For reasoning models (Qwen 3, DeepSeek R1, gpt-oss). Off makes Ask answer in
                  seconds and stops long thinking from using up the answer; sent as
                  reasoning_effort, so leave Model default for servers that do not support it.
                </span>
              </label>
            ) : null}
            {existing?.locality === "cloud" ? (
              <label className="flex items-start gap-2 text-sm md:col-span-2">
                <input
                  type="checkbox"
                  checked={redact}
                  onChange={(e) => setRedact(e.target.checked)}
                  className="mt-1"
                />
                <span>
                  Send IP addresses, user names, host names, and emails as tokens
                  <span className="block text-text-muted">
                    Off by default: marking a source cloud allowed already means its logs may be
                    sent as they are. When on, the model sees tokens such as IP_1a2b3c4d, and
                    answers come back with the real values. Other free text in log lines is still
                    sent.
                  </span>
                </span>
              </label>
            ) : null}
          </OptionalSection>
        </div>
      ) : null}
      {needsAck ? (
        <div
          role="alert"
          className="mt-3 rounded border border-warn bg-sev-medium-bg px-3 py-2 text-sm text-sev-medium-text"
        >
          <p className="font-semibold">This URL is a cloud service.</p>
          <p>
            Events from local-only sources are always blocked from it. Only sources marked cloud
            allowed can be sent, and every call is recorded in the audit log.
          </p>
          <label className="mt-2 flex items-center gap-2">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />I
            understand; add it as a cloud provider
          </label>
        </div>
      ) : null}
      <div className="mt-3">
        <FormError message={error} />
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          disabled={save.isPending || (needsAck && !ack)}
          className="h-9 rounded bg-accent px-4 text-sm font-semibold text-white disabled:opacity-40"
        >
          {existing ? "Save changes" : "Add provider"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="h-9 rounded border border-border-strong px-4 text-sm"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
