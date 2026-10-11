import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, type AlertTargetInput, type AlertTargetKind } from "@/lib/api";

interface TargetFormProps {
  onCreated: (name: string, signingKey: string | null) => void;
  onCancel: () => void;
}

const HELP: Record<AlertTargetKind, string> = {
  slack: "A Slack incoming webhook URL (https://hooks.slack.com/...).",
  teams:
    "A Teams Workflows webhook URL (Power Automate). The old Office 365 connector URLs no longer work.",
  webhook:
    "Any URL that accepts a JSON POST. https is required for public hosts; http is allowed for private addresses, such as ntfy or n8n on your network.",
  email: "An SMTP server. STARTTLS or TLS is required unless the relay runs on this host.",
};

/** Admin: add an alert target. Secrets are write-only (ADR-0007). */
export function TargetForm({ onCreated, onCancel }: TargetFormProps) {
  const client = useQueryClient();
  const [kind, setKind] = useState<AlertTargetKind>("slack");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("587");
  const [security, setSecurity] = useState<"starttls" | "tls" | "none">("starttls");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const save = useMutation({
    mutationFn: () => {
      const body: AlertTargetInput = { name: name.trim(), kind };
      if (kind === "email") {
        body.email = {
          host: host.trim(),
          port: Number(port),
          security,
          username: username.trim() || null,
          from_addr: from.trim(),
          to_addrs: to
            .split(",")
            .map((a) => a.trim())
            .filter(Boolean),
        };
        if (password) body.password = password;
      } else {
        body.url = url.trim();
      }
      return api.createAlertTarget(body);
    },
    onSuccess: async (t) => {
      await client.invalidateQueries({ queryKey: ["alert-targets"] });
      onCreated(t.name, t.signing_key);
    },
  });
  const field = "flex min-w-0 flex-col gap-1 text-sm";
  const input = "h-8 rounded border border-border bg-inset px-2";
  return (
    <form
      aria-label="New alert target"
      className="flex flex-col gap-3 rounded-card border border-border bg-surface p-3"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
        <label className={field}>
          <span className="text-text-secondary">Kind</span>
          <select
            className={input}
            value={kind}
            onChange={(e) => setKind(e.target.value as AlertTargetKind)}
          >
            <option value="slack">Slack</option>
            <option value="teams">Microsoft Teams</option>
            <option value="email">Email (SMTP)</option>
            <option value="webhook">Webhook</option>
          </select>
        </label>
        <label className={field}>
          <span className="text-text-secondary">Name</span>
          <input className={input} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        {kind === "email" ? (
          <>
            <label className={field}>
              <span className="text-text-secondary">SMTP host</span>
              <input
                className={`${input} font-mono`}
                value={host}
                onChange={(e) => setHost(e.target.value)}
              />
            </label>
            <label className={field}>
              <span className="text-text-secondary">Port</span>
              <input
                className={input}
                type="number"
                value={port}
                onChange={(e) => setPort(e.target.value)}
              />
            </label>
            <label className={field}>
              <span className="text-text-secondary">Security</span>
              <select
                className={input}
                value={security}
                onChange={(e) => setSecurity(e.target.value as "starttls" | "tls" | "none")}
              >
                <option value="starttls">STARTTLS</option>
                <option value="tls">TLS</option>
                <option value="none">None (relay on this host only)</option>
              </select>
            </label>
            <label className={field}>
              <span className="text-text-secondary">User name (optional)</span>
              <input
                className={input}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label className={field}>
              <span className="text-text-secondary">Password (optional)</span>
              <input
                className={input}
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <label className={field}>
              <span className="text-text-secondary">From</span>
              <input className={input} value={from} onChange={(e) => setFrom(e.target.value)} />
            </label>
            <label className={field}>
              <span className="text-text-secondary">To (comma separated)</span>
              <input className={input} value={to} onChange={(e) => setTo(e.target.value)} />
            </label>
          </>
        ) : (
          <label className={`${field} col-span-full`}>
            <span className="text-text-secondary">Webhook URL</span>
            <input
              className={`${input} font-mono`}
              type="password"
              autoComplete="off"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
            />
          </label>
        )}
      </div>
      <p className="text-sm text-text-secondary">
        {HELP[kind]} The URL and password are stored encrypted and never shown again. Alerts carry a
        summary only (what fired, when, how many, why, and a link back), never log content.
      </p>
      {save.error ? (
        <p role="alert" className="text-sm text-danger">
          {save.error instanceof ApiError ? save.error.message : "That did not work"}
        </p>
      ) : null}
      <div className="flex gap-2">
        <button
          type="submit"
          className="h-8 rounded bg-accent px-3 font-semibold text-white disabled:opacity-40"
          disabled={!name.trim() || save.isPending}
        >
          Add target
        </button>
        <button type="button" className="h-8 rounded px-3 hover:bg-surface-head" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
