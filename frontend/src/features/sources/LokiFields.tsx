import { useMutation } from "@tanstack/react-query";
import { Field } from "@/features/auth/Field";
import { ApiError, api, type LokiSettings } from "@/lib/api";

interface LokiFieldsProps {
  value: LokiSettings;
  secret: string;
  onChange: (next: LokiSettings) => void;
  onSecret: (secret: string) => void;
}

/** The Loki part of Add source (ADR-0011), with a connection test before saving. */
export function LokiFields({ value, secret, onChange, onSecret }: LokiFieldsProps) {
  const set = <K extends keyof LokiSettings>(key: K, v: LokiSettings[K]) =>
    onChange({ ...value, [key]: v });
  const test = useMutation({
    mutationFn: () => api.testLoki({ ...value, secret: secret || undefined }),
  });
  return (
    <>
      <Field
        label="Loki URL"
        help="The Loki root, for example http://loki.internal:3100. https unless it is a private address."
        value={value.url}
        onChange={(e) => set("url", e.target.value)}
        className="font-mono"
        required
      />
      <Field
        label="Query"
        help='A label selector, optionally with line filters: {job="syslog", host=~"fw.*"} |= "sshd"'
        value={value.query}
        onChange={(e) => set("query", e.target.value)}
        className="font-mono"
        required
      />
      <div className="flex flex-col gap-1">
        <label htmlFor="loki-auth" className="text-sm font-semibold">
          Sign-in
        </label>
        <select
          id="loki-auth"
          value={value.auth}
          onChange={(e) => set("auth", e.target.value as LokiSettings["auth"])}
          className="h-9 rounded border border-border-strong bg-inset px-2 text-sm text-text"
        >
          <option value="none">None</option>
          <option value="basic">Username and password</option>
          <option value="bearer">Bearer token</option>
        </select>
      </div>
      {value.auth === "basic" ? (
        <Field
          label="Username"
          value={value.username ?? ""}
          onChange={(e) => set("username", e.target.value)}
          autoComplete="off"
        />
      ) : null}
      {value.auth !== "none" ? (
        <Field
          label={value.auth === "basic" ? "Password" : "Token"}
          help="Stored encrypted. It is never shown again."
          type="password"
          value={secret}
          onChange={(e) => onSecret(e.target.value)}
          autoComplete="new-password"
        />
      ) : null}
      <Field
        label="Tenant (optional)"
        help="Sent as X-Scope-OrgID, for multi-tenant Loki."
        value={value.tenant ?? ""}
        onChange={(e) => set("tenant", e.target.value || null)}
        className="font-mono"
      />
      <Field
        label="On first run, read back (hours)"
        type="number"
        min={0}
        max={87600}
        value={value.backfill_hours}
        onChange={(e) => set("backfill_hours", Number(e.target.value))}
      />
      <div className="flex flex-col gap-2 md:col-span-2">
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => test.mutate()}
            disabled={test.isPending || !value.url || !value.query}
            className="h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head disabled:opacity-50"
          >
            {test.isPending ? "Testing…" : "Test connection"}
          </button>
          <span className="text-sm text-text-muted">Reads up to 100 lines from the last hour</span>
        </div>
        {test.error ? (
          <p role="alert" className="text-sm text-danger">
            {test.error instanceof ApiError ? test.error.message : "The test did not work"}
          </p>
        ) : null}
        {test.data ? (
          <div role="status" className="text-sm">
            <p className={test.data.lines ? "text-ok" : "text-warn"}>
              {test.data.lines
                ? `Connected: ${test.data.lines} lines in the last hour from ${test.data.streams.length} ${test.data.streams.length === 1 ? "stream" : "streams"}`
                : "Connected, but no lines matched in the last hour"}
            </p>
            {test.data.streams.length ? (
              <ul className="mt-1 font-mono text-text-secondary">
                {test.data.streams.map((s, i) => (
                  <li key={i}>
                    {"{"}
                    {Object.entries(s)
                      .map(([k, v]) => `${k}="${v}"`)
                      .join(", ")}
                    {"}"}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </div>
    </>
  );
}
