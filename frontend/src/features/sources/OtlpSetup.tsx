import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { PRODUCT_NAME } from "@/lib/branding";

/** The OTLP base address senders use (ADR-0015 row 3). */
export function otlpEndpoint(): string {
  return `${window.location.origin}/api/otlp`;
}

function claudeCodeSettings(endpoint: string, token: string): string {
  return JSON.stringify(
    {
      env: {
        CLAUDE_CODE_ENABLE_TELEMETRY: "1",
        OTEL_LOGS_EXPORTER: "otlp",
        OTEL_METRICS_EXPORTER: "otlp",
        OTEL_EXPORTER_OTLP_PROTOCOL: "http/json",
        OTEL_EXPORTER_OTLP_ENDPOINT: endpoint,
        OTEL_EXPORTER_OTLP_HEADERS: `Authorization=Bearer ${token}`,
        OTEL_LOG_TOOL_DETAILS: "1",
        OTEL_LOG_USER_PROMPTS: "1",
      },
    },
    null,
    2,
  );
}

async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function CopyBlock({ label, text }: { label: string; text: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2 text-sm">
        <span className="font-semibold">{label}</span>
        <button
          type="button"
          onClick={() => void copy(text).then(setDone)}
          className="ml-auto rounded px-2 py-0.5 text-accent-text hover:bg-surface-head"
        >
          {done ? "Copied" : "Copy"}
        </button>
      </div>
      <pre
        aria-label={label}
        className="m-0 overflow-x-auto whitespace-pre-wrap break-all rounded border border-border bg-inset px-3 py-2 font-mono text-sm"
      >
        {text}
      </pre>
    </div>
  );
}

/** Download the generated collector config for an agent group (ADR-0017 row 2). */
export async function downloadAgentConfig(sourceId: string, os: "windows" | "linux") {
  const yaml = await api.agentConfig(sourceId, os);
  const url = URL.createObjectURL(new Blob([yaml], { type: "application/yaml" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${PRODUCT_NAME.toLowerCase()}-agent-${sourceId}-${os}.yaml`;
  a.click();
  URL.revokeObjectURL(url);
}

interface OtlpTokenPanelProps {
  sourceId: string;
  token: string;
  onDone: () => void;
}

/** Shown once, right after an OTLP source is made or its token replaced. */
export function OtlpTokenPanel({ sourceId, token, onDone }: OtlpTokenPanelProps) {
  const endpoint = otlpEndpoint();
  const download = useMutation({
    mutationFn: (os: "windows" | "linux") => downloadAgentConfig(sourceId, os),
  });
  return (
    <section
      aria-label="Ingest token"
      className="flex flex-col gap-3 rounded-card border border-accent bg-surface p-4"
    >
      <h2 className="text-base font-semibold">
        Ingest token for <span className="font-mono">{sourceId}</span>
      </h2>
      <p className="text-sm text-warn">
        Shown once. It can only send data into this source; replace it from the Sources list if it
        leaks.
      </p>
      <CopyBlock label="Token" text={token} />
      <CopyBlock label="OTLP endpoint (protocol http/json)" text={endpoint} />
      <CopyBlock
        label="Claude Code managed settings (env block)"
        text={claudeCodeSettings(endpoint, token)}
      />
      <p className="text-sm text-text-secondary">
        With these settings {PRODUCT_NAME} records who used Claude Code, tokens, cost, tools, and
        MCP servers. Prompt text and tool input are scanned for sensitive data (keys, card numbers,
        SSNs) and then dropped: only the categories are kept. Remove the last two lines to send
        neither.
      </p>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold">Endpoint agent config</span>
        <button
          type="button"
          onClick={() => download.mutate("windows")}
          className="h-7 rounded border border-border-strong px-3 hover:bg-surface-head"
        >
          Windows
        </button>
        <button
          type="button"
          onClick={() => download.mutate("linux")}
          className="h-7 rounded border border-border-strong px-3 hover:bg-surface-head"
        >
          Linux
        </button>
        <span className="text-text-muted">
          OpenTelemetry Collector; reads the token from a file
        </span>
      </div>
      {download.isError ? (
        <p role="alert" className="text-sm text-danger">
          {download.error instanceof ApiError ? download.error.message : "Download failed"}
        </p>
      ) : null}
      <div>
        <button
          type="button"
          onClick={onDone}
          className="h-8 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110"
        >
          Done
        </button>
      </div>
    </section>
  );
}

interface OtlpControlsProps {
  sourceId: string;
  keepContent: boolean;
  canManage: boolean;
}

/** Row controls for an OTLP source: replace the token, agent configs, keep content. */
export function OtlpControls({ sourceId, keepContent, canManage }: OtlpControlsProps) {
  const [token, setToken] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const rotate = useMutation({
    mutationFn: () => api.rotateOtlpToken(sourceId),
    onSuccess: (r) => {
      setConfirming(false);
      setToken(r.token);
    },
  });
  const keep = useMutation({ mutationFn: (v: boolean) => api.setKeepContent(sourceId, v) });
  const download = useMutation({
    mutationFn: (os: "windows" | "linux") => downloadAgentConfig(sourceId, os),
  });
  const kept = keep.data?.otlp_keep_content ?? keepContent;
  return (
    <div className="flex flex-col gap-1 font-sans text-sm">
      <span className="text-text-secondary">OTLP receiver · {otlpEndpoint()}</span>
      {canManage ? (
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {confirming ? (
            <>
              <span className="text-warn">The current token stops working.</span>
              <button
                type="button"
                onClick={() => rotate.mutate()}
                className="text-danger hover:underline"
              >
                Replace
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className="text-text-secondary"
              >
                Keep
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="text-accent-text hover:underline"
            >
              New token
            </button>
          )}
          <span className="text-text-muted">Agent config:</span>
          <button
            type="button"
            onClick={() => download.mutate("windows")}
            className="text-accent-text hover:underline"
          >
            Windows
          </button>
          <button
            type="button"
            onClick={() => download.mutate("linux")}
            className="text-accent-text hover:underline"
          >
            Linux
          </button>
        </span>
      ) : null}
      {canManage ? (
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={kept}
            disabled={keep.isPending}
            onChange={(e) => keep.mutate(e.target.checked)}
            className="mt-1"
          />
          <span className={kept ? "text-warn" : "text-text-secondary"}>
            Keep prompt and tool content
            {kept
              ? ": stored in the lake and backups; anyone with this source can read it"
              : " (off: only sensitive-data categories are kept)"}
          </span>
        </label>
      ) : null}
      {token ? (
        <div className="mt-1 flex flex-col gap-1">
          <CopyBlock label="New token (shown once)" text={token} />
          <button
            type="button"
            onClick={() => setToken(null)}
            className="self-start text-text-secondary hover:text-text"
          >
            Hide
          </button>
        </div>
      ) : null}
      {rotate.isError || keep.isError || download.isError ? (
        <span role="alert" className="text-danger">
          {(rotate.error ?? keep.error ?? download.error) instanceof ApiError
            ? ((rotate.error ?? keep.error ?? download.error) as ApiError).message
            : "That did not work"}
        </span>
      ) : null}
    </div>
  );
}
