import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, api } from "@/lib/api";
import { PRODUCT_NAME } from "@/lib/branding";

interface ClaudePluginProps {
  sourceId: string;
  keepContent: boolean;
  onClose: () => void;
}

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/** Download the observe-only hooks plugin for this source (ADR-0026): the server address
 * and a new token are written into it, with the pilot list. Admins upload the zip in the
 * Claude admin console. */
export function ClaudePlugin({ sourceId, keepContent, onClose }: ClaudePluginProps) {
  const [server, setServer] = useState("");
  const [pilot, setPilot] = useState("");
  const info = useQuery({ queryKey: ["claude-plugin"], queryFn: api.claudePluginInfo });
  const users = pilot.split(/[\s,;]+/).filter(Boolean);
  const download = useMutation({
    mutationFn: () =>
      api.claudePlugin(sourceId, {
        ...(server.trim() ? { server_url: server.trim() } : {}),
        pilot_users: users,
      }),
    onSuccess: ({ blob }) =>
      save(blob, `${PRODUCT_NAME.toLowerCase()}-claude-hooks-${sourceId}.zip`),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    download.mutate();
  };
  return (
    <form
      aria-label={`Claude plugin for ${sourceId}`}
      onSubmit={submit}
      className="mt-1 flex max-w-xl flex-col gap-2 rounded border border-border bg-inset p-3"
    >
      <p className="text-text-secondary">
        Observe-only hooks for Claude Code and Cowork: one record per session start, prompt, tool
        call, tool result, and stop. It never blocks anything. Sends{" "}
        {keepContent
          ? "prompt text and tool input and output too, because this source keeps content."
          : "metadata only: no prompt text, tool input, or tool output."}
      </p>
      <label className="flex flex-col gap-1">
        <span className="font-semibold">Server address</span>
        <input
          aria-label="Server address"
          value={server}
          onChange={(e) => setServer(e.target.value)}
          placeholder="https://siem.example.internal:8080 (blank: this server's public address)"
          className="h-8 rounded border border-border-strong bg-surface px-2 font-mono"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="font-semibold">Pilot users</span>
        <textarea
          aria-label="Pilot users"
          value={pilot}
          onChange={(e) => setPilot(e.target.value)}
          rows={2}
          placeholder="Claude account emails or OS user names, for example dana@example.com"
          className="rounded border border-border-strong bg-surface px-2 py-1 font-mono"
        />
        <span className="text-text-muted">
          {users.length
            ? `Only these ${users.length} people send, wherever the plugin is installed.`
            : "Empty: everyone who has the plugin sends."}
        </span>
      </label>
      <p className="text-warn">
        Downloading issues a new token for this source: earlier copies of the plugin and anything
        else sending to this source stop until updated. Use a source just for the plugin.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="submit"
          disabled={download.isPending}
          className="h-8 rounded bg-accent px-3 font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {download.isPending ? "Preparing" : "Download plugin"}
        </button>
        <button type="button" onClick={onClose} className="h-8 rounded px-3">
          Close
        </button>
        {info.data ? (
          <span className="text-text-muted">
            Version {info.data.version}, script SHA-256{" "}
            <span className="break-all font-mono">{info.data.script_sha256}</span>
          </span>
        ) : null}
      </div>
      {download.isSuccess ? (
        <p role="status" className="text-ok">
          Downloaded. Upload the zip in the Claude admin console (Organization settings, Plugins and
          skills), then set it to Installed by default or Required.
        </p>
      ) : null}
      {download.isError ? (
        <p role="alert" className="text-danger">
          {download.error instanceof ApiError ? download.error.message : "Download failed"}
        </p>
      ) : null}
    </form>
  );
}
