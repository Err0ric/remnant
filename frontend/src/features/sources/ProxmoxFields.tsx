import { useMutation } from "@tanstack/react-query";
import { Field } from "@/features/auth/Field";
import { OptionalSection } from "@/components/forms/OptionalSection";
import { ApiCredentialsFields } from "./ApiCredentialsFields";
import { feedResult } from "./ApiSourceFields";
import { ApiError, api, type ApiCredentials, type ProxmoxSettings } from "@/lib/api";

export const PROXMOX_DEFAULTS: ProxmoxSettings = {
  host: "",
  port: 8006,
  token_id: "",
  ca_pem: null,
  poll_minutes: 15,
};

/** Shown in the form and on the Sources list until the owner's homelab results are in. */
export const PROXMOX_VERIFIED = "Verified on Proxmox 8 and 9: pending";

const AREA =
  "min-h-24 rounded border border-border-control bg-inset px-2 py-1.5 font-mono text-sm text-text";

interface ProxmoxFieldsProps {
  /** required: host and token; optional: CA and schedule; test: the connection test. */
  part: "required" | "optional" | "test";
  value: ProxmoxSettings;
  credentials: ApiCredentials;
  onChange: (next: ProxmoxSettings) => void;
  onCredentials: (next: ApiCredentials) => void;
}

/** Settings for a Proxmox VE inventory source (ADR-0045), with a test before saving. */
export function ProxmoxFields({
  part,
  value,
  credentials,
  onChange,
  onCredentials,
}: ProxmoxFieldsProps) {
  const set = <K extends keyof ProxmoxSettings>(key: K, v: ProxmoxSettings[K]) =>
    onChange({ ...value, [key]: v });
  const test = useMutation({
    mutationFn: () => api.testApiSource({ kind: "proxmox", proxmox: value, credentials }),
  });

  if (part === "required") {
    return (
      <>
        <Field
          label="Proxmox host"
          help="A node or cluster host name, for example pve1.example.internal. The certificate is always checked."
          value={value.host}
          onChange={(e) => set("host", e.target.value.trim())}
          className="font-mono"
          required
        />
        <Field
          label="Port"
          type="number"
          min={1}
          max={65535}
          value={value.port}
          onChange={(e) => set("port", Number(e.target.value))}
        />
        <Field
          label="API token ID"
          help="user@realm!name, for a token with the PVEAuditor role only. A token that can change anything is refused. See docs/install/proxmox.md."
          value={value.token_id}
          onChange={(e) => set("token_id", e.target.value.trim())}
          className="font-mono"
          required
        />
        <ApiCredentialsFields kind="proxmox" value={credentials} onChange={onCredentials} />
      </>
    );
  }

  if (part === "optional") {
    const summary = [
      value.ca_pem ? "Pinned CA" : "System CA store",
      `Every ${value.poll_minutes} min`,
    ].join(" · ");
    return (
      <OptionalSection title="Certificate and schedule" summary={summary}>
        <div className="flex flex-col gap-1">
          <label htmlFor="proxmox-ca" className="text-sm font-semibold">
            Cluster CA (PEM)
          </label>
          <textarea
            id="proxmox-ca"
            value={value.ca_pem ?? ""}
            onChange={(e) => set("ca_pem", e.target.value || null)}
            placeholder="-----BEGIN CERTIFICATE-----"
            spellCheck={false}
            className={AREA}
          />
          <p className="text-sm text-text-muted">
            For a self-signed cluster: /etc/pve/pve-root-ca.pem. When set, only this CA is trusted.
          </p>
        </div>
        <Field
          label="Read every (minutes)"
          help="Events are written only when a guest appears, changes, or disappears, plus one a day per guest."
          type="number"
          min={5}
          max={1440}
          value={value.poll_minutes}
          onChange={(e) => set("poll_minutes", Number(e.target.value))}
        />
      </OptionalSection>
    );
  }

  return (
    <div className="flex flex-col gap-2 md:col-span-2">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => test.mutate()}
          disabled={test.isPending || !value.host || !value.token_id || !credentials.token_secret}
          className="h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head disabled:opacity-50"
        >
          {test.isPending ? "Testing…" : "Test connection"}
        </button>
        <span className="text-sm text-text-muted">{PROXMOX_VERIFIED}</span>
      </div>
      {test.error ? (
        <p role="alert" className="text-sm text-danger">
          {test.error instanceof ApiError ? test.error.message : "The test did not work"}
        </p>
      ) : null}
      {test.data ? (
        <ul role="status" className="flex flex-col gap-0.5 text-sm">
          {Object.entries(test.data.feeds).map(([check, result]) => (
            <li key={check} className="flex flex-wrap gap-2">
              <span className="font-mono">{check}</span>
              <span className={result.startsWith("ok") ? "text-ok" : "text-warn"}>
                {feedResult(result)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
