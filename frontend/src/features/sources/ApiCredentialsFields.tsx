import { Field } from "@/features/auth/Field";
import type { ApiCredentials } from "@/lib/api";

interface ApiCredentialsFieldsProps {
  kind: "m365" | "anthropic";
  /** Microsoft 365 only: which credential the app registration uses. */
  auth?: "certificate" | "secret";
  value: ApiCredentials;
  onChange: (next: ApiCredentials) => void;
}

const AREA =
  "min-h-24 rounded border border-border-strong bg-inset px-2 py-1.5 font-mono text-sm text-text";

/** Write-only credential inputs for an API source; stored encrypted, never shown again. */
export function ApiCredentialsFields({ kind, auth, value, onChange }: ApiCredentialsFieldsProps) {
  if (kind === "anthropic") {
    return (
      <Field
        label="API key"
        help="An Admin key (usage, cost, Claude Code), Analytics key, or Compliance key. Starts with sk-ant-. Stored encrypted."
        type="password"
        value={value.api_key ?? ""}
        onChange={(e) => onChange({ api_key: e.target.value.trim() })}
        autoComplete="new-password"
        className="font-mono"
        required
      />
    );
  }
  if (auth === "secret") {
    return (
      <Field
        label="Client secret"
        help="From the app registration's Certificates and secrets page. Stored encrypted. A certificate is safer: secrets expire within two years."
        type="password"
        value={value.client_secret ?? ""}
        onChange={(e) => onChange({ client_secret: e.target.value })}
        autoComplete="new-password"
        required
      />
    );
  }
  return (
    <>
      <div className="flex flex-col gap-1">
        <label htmlFor="m365-cert" className="text-sm font-semibold">
          Certificate (PEM)
        </label>
        <textarea
          id="m365-cert"
          value={value.certificate_pem ?? ""}
          onChange={(e) => onChange({ ...value, certificate_pem: e.target.value })}
          placeholder="-----BEGIN CERTIFICATE-----"
          spellCheck={false}
          className={AREA}
          required
        />
        <p className="text-sm text-text-muted">
          The public certificate you uploaded to the app registration.
        </p>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="m365-key" className="text-sm font-semibold">
          Private key (PEM, unencrypted)
        </label>
        <textarea
          id="m365-key"
          value={value.private_key_pem ?? ""}
          onChange={(e) => onChange({ ...value, private_key_pem: e.target.value })}
          placeholder="-----BEGIN PRIVATE KEY-----"
          spellCheck={false}
          autoComplete="off"
          className={AREA}
          required
        />
        <p className="text-sm text-text-muted">Stored encrypted. It is never shown again.</p>
      </div>
    </>
  );
}
