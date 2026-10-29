import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, api, type PluginPlatform } from "@/lib/api";
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
const PLATFORMS: { id: PluginPlatform; label: string; note: string }[] = [
  { id: "windows", label: "Windows", note: "Windows PowerShell 5.1, nothing to install" },
  { id: "posix", label: "macOS and Linux", note: "sh and curl" },
];

export function ClaudePlugin({ sourceId, keepContent, onClose }: ClaudePluginProps) {
  const [server, setServer] = useState("");
  const [pilot, setPilot] = useState("");
  const [platform, setPlatform] = useState<PluginPlatform>("windows");
  const [managed, setManaged] = useState(false);
  const [trust, setTrust] = useState(true);
  const info = useQuery({ queryKey: ["claude-plugin"], queryFn: api.claudePluginInfo });
  const users = pilot.split(/[\s,;]+/).filter(Boolean);
  const download = useMutation({
    mutationFn: () =>
      api.claudePlugin(sourceId, {
        ...(server.trim() ? { server_url: server.trim() } : {}),
        pilot_users: users,
        platform,
        managed,
        trust_server_certificate: trust,
      }),
    onSuccess: ({ blob }) =>
      save(
        blob,
        `${PRODUCT_NAME.toLowerCase()}-claude-hooks-${platform}-${managed ? "managed" : "plugin"}-${sourceId}.zip`,
      ),
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
        Observe-only hooks for Claude Code: one record per session start, prompt, tool call, tool
        result or failure, turn end, and session end. It never blocks anything. Sends{" "}
        {keepContent
          ? "prompt text and tool input and output too, because this source keeps content."
          : "metadata only: no prompt text, tool input, or tool output."}
      </p>
      <fieldset className="flex flex-col gap-1">
        <legend className="mb-1 font-semibold">Platform</legend>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {PLATFORMS.map((p) => (
            <label key={p.id} className="flex items-center gap-2">
              <input
                type="radio"
                name={`platform-${sourceId}`}
                checked={platform === p.id}
                onChange={() => setPlatform(p.id)}
              />
              {p.label} <span className="text-text-muted">({p.note})</span>
            </label>
          ))}
        </div>
        <span className="text-text-muted">
          One plugin per platform: publish each to the people on that platform.
        </span>
      </fieldset>
      <fieldset className="flex flex-col gap-1">
        <legend className="mb-1 font-semibold">Where the address and token live</legend>
        <label className="flex items-start gap-2">
          <input
            type="radio"
            name={`managed-${sourceId}`}
            checked={!managed}
            onChange={() => setManaged(false)}
            className="mt-1"
          />
          <span>
            In the plugin <span className="text-text-muted">(a pilot: nothing else to deploy)</span>
          </span>
        </label>
        <label className="flex items-start gap-2">
          <input
            type="radio"
            name={`managed-${sourceId}`}
            checked={managed}
            onChange={() => setManaged(true)}
            className="mt-1"
          />
          <span>
            In a machine-wide file{" "}
            <span className="text-text-muted">
              (deployed by your endpoint management tool, writable by administrators only; it wins
              over the plugin's copy)
            </span>
          </span>
        </label>
      </fieldset>
      {info.data?.self_signed ? (
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={trust}
            onChange={(e) => setTrust(e.target.checked)}
            className="mt-1"
          />
          <span>
            Include this server's self-signed certificate{" "}
            <span className="text-text-muted">
              (the scripts check the server against it; without it they use the computer's trusted
              certificates)
            </span>
          </span>
        </label>
      ) : null}
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
          {download.isPending ? "Preparing" : managed ? "Download bundle" : "Download plugin"}
        </button>
        <button type="button" onClick={onClose} className="h-8 rounded px-3">
          Close
        </button>
        {info.data ? (
          <span className="text-text-muted">
            Version {info.data.version}, script SHA-256{" "}
            <span className="break-all font-mono">{info.data.scripts[platform]}</span>
          </span>
        ) : null}
      </div>
      {download.isSuccess ? (
        <p role="status" className="text-ok">
          {managed
            ? "Downloaded. The bundle's README says where hooks.conf goes; upload the plugin zip inside it in the Claude admin console (Organization settings, Plugins and skills)."
            : "Downloaded. Upload the zip in the Claude admin console (Organization settings, Plugins and skills), then set it to Installed by default or Required."}
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
