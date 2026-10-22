import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Field } from "@/features/auth/Field";
import { ANTHROPIC_DEFAULTS, ApiSourceFields, M365_DEFAULTS } from "./ApiSourceFields";
import { LokiFields } from "./LokiFields";
import { OtlpTokenPanel } from "./OtlpSetup";
import { ParserSelect } from "./ParserSelect";
import { AUTO_PARSER, parserHelp, parserName } from "@/lib/parsers";
import { OptionalSection } from "@/components/forms/OptionalSection";
import { FormError } from "@/features/auth/FormError";
import {
  ApiError,
  api,
  type AnthropicSettings,
  type ApiCredentials,
  type LokiSettings,
  type M365Settings,
  type SourceFormat,
  type SourceInput,
  type SourceKind,
  type SyslogSettings,
} from "@/lib/api";

const ID_PATTERN = /^[a-z0-9][a-z0-9_]{0,63}$/;

const FORMATS: SourceFormat[] = ["syslog", "json", "csv"];

const KIND_HELP: Record<SourceKind, string> = {
  file: "Files are read as they grow; rotated files are followed.",
  loki: "Lines are copied from Loki every 30 seconds and parsed like a file.",
  otlp: "Senders push OTLP JSON with this source's token, which is shown once after you add it.",
  m365: "Read every 5 minutes with a read-only app registration. See docs/install/m365.md for the exact permissions.",
  anthropic:
    "Reports are read every 5 minutes once each hour or day is final. No chat content is read.",
  syslog:
    "Devices send syslog to this server on the port below. In Docker, publish the port too (docs/install/syslog-listener.md).",
};

const DEFAULT_PORT: Record<SyslogSettings["protocol"], number> = {
  udp: 5514,
  tcp: 5514,
  tls: 6514,
};

interface AddSourceFormProps {
  allowedRoots: string[];
  /** Values to start from, e.g. a discovery suggestion. The admin can change them all. */
  initial?: Partial<SourceInput>;
  onDone: () => void;
}

export function AddSourceForm({ allowedRoots, initial, onDone }: AddSourceFormProps) {
  const client = useQueryClient();
  const [form, setForm] = useState<SourceInput>({
    source_id: "",
    format: "syslog",
    path: allowedRoots[0] ?? "",
    glob: "**/*.log",
    timezone: "UTC",
    retention_days: 30,
    // Mixed streams are the common case (ADR-0012); a discovery suggestion overrides this.
    template_id: AUTO_PARSER,
    ...initial,
  });
  const [kind, setKind] = useState<SourceKind>("file");
  // An OTLP source's token, shown once after it is made (ADR-0015 row 3).
  const [created, setCreated] = useState<{ id: string; token: string } | null>(null);
  const [loki, setLoki] = useState<LokiSettings>({
    url: "",
    query: "",
    auth: "none",
    backfill_hours: 24,
  });
  const [lokiSecret, setLokiSecret] = useState("");
  const [m365, setM365] = useState<M365Settings>(M365_DEFAULTS);
  const [anthropic, setAnthropic] = useState<AnthropicSettings>(ANTHROPIC_DEFAULTS);
  const [credentials, setCredentials] = useState<ApiCredentials>({});
  const [syslog, setSyslog] = useState<SyslogSettings>({
    protocol: "udp",
    port: DEFAULT_PORT.udp,
    allowed_senders: [],
  });
  const [senders, setSenders] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  // F27: the Loki addresses existing sources use (admins see them; others never add sources).
  const existing = useQuery({ queryKey: ["source-list"], queryFn: api.sources });
  const knownLokiUrls = [
    ...new Set(
      (existing.data ?? [])
        .map((s) => (s.kind === "loki" ? s.loki?.url : undefined))
        .filter((u): u is string => Boolean(u)),
    ),
  ];
  const templates = useQuery({
    queryKey: ["templates"],
    queryFn: api.templates,
    staleTime: 60_000,
  });
  const set = <K extends keyof SourceInput>(key: K, value: SourceInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const add = useMutation({
    mutationFn: api.addSource,
    onSuccess: async (res) => {
      await client.invalidateQueries({ queryKey: ["source-list"] });
      await client.invalidateQueries({ queryKey: ["sources"] }); // Search filter list
      if (res.otlp_token) setCreated({ id: res.source_id, token: res.otlp_token });
      else onDone();
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!ID_PATTERN.test(form.source_id)) {
      setLocalError(
        "Source ID: lowercase letters, digits, and underscores, starting with a letter or digit.",
      );
      return;
    }
    setLocalError(null);
    if (kind === "otlp") {
      add.mutate({
        ...form,
        kind: "otlp",
        format: "json",
        template_id: form.template_id ?? "auto",
        path: "",
        glob: "*",
      });
      return;
    }
    if (kind === "m365" || kind === "anthropic") {
      add.mutate({
        ...form,
        kind,
        format: "json",
        path: "",
        glob: "*",
        m365: kind === "m365" ? m365 : null,
        anthropic: kind === "anthropic" ? anthropic : null,
        credentials,
      });
      return;
    }
    if (kind === "syslog") {
      add.mutate({
        ...form,
        kind: "syslog",
        format: "syslog",
        path: "",
        glob: "*",
        syslog: {
          ...syslog,
          allowed_senders: senders
            .split(/[\s,]+/)
            .map((x) => x.trim())
            .filter(Boolean),
        },
      });
      return;
    }
    if (kind === "loki") {
      add.mutate({
        ...form,
        kind: "loki",
        path: "",
        glob: "*",
        loki: { ...loki, url: loki.url.trim(), query: loki.query.trim() },
        loki_secret: loki.auth !== "none" && lokiSecret ? lokiSecret : undefined,
      });
      return;
    }
    add.mutate(form);
  };

  const serverError = add.error instanceof ApiError ? add.error.message : null;
  if (created) {
    return <OtlpTokenPanel sourceId={created.id} token={created.token} onDone={onDone} />;
  }

  return (
    <form
      onSubmit={submit}
      aria-label="Add source"
      className="rounded-card border border-border bg-surface p-4"
    >
      <h2 className="mb-3 text-base font-semibold">Add source</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Field
          label="Source ID"
          help="Used in queries, e.g. linux_auth or paloalto_traffic. Cannot be changed later."
          value={form.source_id}
          onChange={(e) => set("source_id", e.target.value.trim())}
          className="font-mono"
          required
        />
        <div className="flex flex-col gap-1">
          <label htmlFor="source-kind" className="text-sm font-semibold">
            Reads from
          </label>
          <select
            id="source-kind"
            value={kind}
            onChange={(e) => {
              const next = e.target.value as SourceKind;
              setKind(next);
              setCredentials({});
              if (next === "otlp" || next === "m365")
                setForm((f) => ({ ...f, format: "json", template_id: AUTO_PARSER }));
              if (next === "syslog") setForm((f) => ({ ...f, format: "syslog" }));
              if (next === "anthropic")
                setForm((f) => ({ ...f, format: "json", template_id: "anthropic_reports" }));
            }}
            className="h-9 rounded border border-border-strong bg-inset px-2 text-sm text-text"
          >
            <option value="file">A file or folder on this server</option>
            <option value="syslog">Syslog sent over the network (UDP, TCP, TLS)</option>
            <option value="loki">Grafana Loki</option>
            <option value="otlp">OpenTelemetry: Claude Code, endpoint agents, MCP inventory</option>
            <option value="m365">Microsoft 365: audit, Entra sign-ins, alerts</option>
            <option value="anthropic">Anthropic: usage, cost, Claude Code, audit</option>
          </select>
          <p className="text-sm text-text-muted">{KIND_HELP[kind]}</p>
        </div>
        {kind === "loki" ? (
          <LokiFields
            part="required"
            value={loki}
            secret={lokiSecret}
            onChange={setLoki}
            onSecret={setLokiSecret}
            knownUrls={knownLokiUrls}
          />
        ) : kind === "m365" || kind === "anthropic" ? (
          <ApiSourceFields
            part="required"
            kind={kind}
            m365={m365}
            anthropic={anthropic}
            credentials={credentials}
            onM365={setM365}
            onAnthropic={setAnthropic}
            onCredentials={setCredentials}
          />
        ) : kind === "syslog" ? (
          <div className="flex flex-col gap-1">
            <span id="listener-label" className="text-sm font-semibold">
              Listen on
            </span>
            <div className="flex gap-2" role="group" aria-labelledby="listener-label">
              <select
                aria-label="Protocol"
                value={syslog.protocol}
                onChange={(e) => {
                  const protocol = e.target.value as SyslogSettings["protocol"];
                  // Follow the usual port for the protocol until the admin picks one.
                  setSyslog((v) => ({
                    ...v,
                    protocol,
                    port: v.port === DEFAULT_PORT[v.protocol] ? DEFAULT_PORT[protocol] : v.port,
                  }));
                }}
                className="h-9 rounded border border-border-strong bg-inset px-2 text-sm text-text"
              >
                <option value="udp">UDP</option>
                <option value="tcp">TCP</option>
                <option value="tls">TLS (encrypted TCP)</option>
              </select>
              <input
                aria-label="Port"
                type="number"
                min={1024}
                max={65535}
                required
                value={syslog.port}
                onChange={(e) => setSyslog((v) => ({ ...v, port: Number(e.target.value) }))}
                className="h-9 w-28 rounded border border-border-strong bg-inset px-2 font-mono text-sm text-text"
              />
            </div>
            <p className="text-sm text-text-muted">
              {syslog.protocol === "tls"
                ? "Uses this server's certificate. Senders must trust it."
                : "Plain text on the network. Use TLS when logs cross networks you do not control."}
            </p>
          </div>
        ) : kind === "otlp" ? null : (
          <Field
            label="File or folder"
            help={
              allowedRoots.length
                ? `Must be inside: ${allowedRoots.join(", ")}`
                : "No folders are allowed yet. Set paths.allowed_roots on the server."
            }
            value={form.path}
            onChange={(e) => set("path", e.target.value)}
            className="font-mono"
            required
          />
        )}
        {kind === "m365" || kind === "anthropic" ? (
          <ApiSourceFields
            part="optional"
            kind={kind}
            m365={m365}
            anthropic={anthropic}
            credentials={credentials}
            onM365={setM365}
            onAnthropic={setAnthropic}
            onCredentials={setCredentials}
          />
        ) : null}
        <OptionalSection
          title={kind === "loki" ? "Sign-in, parsing, and retention" : "Parsing and retention"}
          summary={[
            `Parser: ${parserName(form.template_id, form.format, templates.data ?? [])}`,
            kind === "file" ? `Pattern: ${form.glob}` : null,
            kind === "loki" ? `Sign-in: ${loki.auth === "none" ? "none" : loki.auth}` : null,
            kind === "file" || kind === "loki" || kind === "syslog"
              ? `Time zone: ${form.timezone}`
              : null,
            kind === "syslog"
              ? senders.trim()
                ? "Senders: listed"
                : "Senders: private networks"
              : null,
            `Keep ${form.retention_days} days`,
          ]
            .filter(Boolean)
            .join(" · ")}
          defaultOpen={Boolean(initial?.template_id)}
        >
          <div className="flex flex-col gap-1">
            <label htmlFor="source-parser" className="text-sm font-semibold">
              Parser
            </label>
            <ParserSelect
              id="source-parser"
              templateId={form.template_id}
              format={form.format}
              templates={templates.data ?? []}
              formats={FORMATS}
              onChange={(templateId, format) =>
                setForm((f) => ({ ...f, template_id: templateId, format }))
              }
            />
            <p className="text-sm text-text-muted">
              {parserHelp(form.template_id, templates.data ?? [])}
            </p>
          </div>
          {kind === "loki" ? (
            <LokiFields
              part="optional"
              value={loki}
              secret={lokiSecret}
              onChange={setLoki}
              onSecret={setLokiSecret}
            />
          ) : null}
          {kind === "file" ? (
            <Field
              label="File pattern"
              help="For folders. **/*.log matches every .log file in all subfolders."
              value={form.glob}
              onChange={(e) => set("glob", e.target.value)}
              className="font-mono"
            />
          ) : null}
          {kind === "syslog" ? (
            <div className="flex flex-col gap-1">
              <label htmlFor="listener-senders" className="text-sm font-semibold">
                Allowed senders
              </label>
              <textarea
                id="listener-senders"
                aria-describedby="listener-senders-help"
                rows={3}
                value={senders}
                onChange={(e) => setSenders(e.target.value)}
                placeholder="192.168.1.0/24"
                className="rounded border border-border-strong bg-inset px-2 py-1.5 font-mono text-sm text-text"
              />
              <p id="listener-senders-help" className="text-sm text-text-muted">
                Addresses or networks, one per line. Empty accepts private networks only. Messages
                from anywhere else are dropped and counted.
              </p>
            </div>
          ) : null}
          {kind === "file" || kind === "loki" || kind === "syslog" ? (
            <Field
              label="Time zone"
              help="For syslog lines without a zone, e.g. America/Los_Angeles."
              value={form.timezone}
              onChange={(e) => set("timezone", e.target.value)}
            />
          ) : null}
          <Field
            label="Keep data for (days)"
            type="number"
            min={1}
            max={3650}
            value={form.retention_days}
            onChange={(e) => set("retention_days", Number(e.target.value))}
          />
        </OptionalSection>
        {kind === "m365" || kind === "anthropic" ? (
          <ApiSourceFields
            part="test"
            kind={kind}
            m365={m365}
            anthropic={anthropic}
            credentials={credentials}
            onM365={setM365}
            onAnthropic={setAnthropic}
            onCredentials={setCredentials}
          />
        ) : null}
      </div>
      <p className="mt-3 text-sm text-text-muted">
        New sources are local only: their data is never sent to a cloud AI provider. An
        administrator can allow cloud for a source later, from this list.
      </p>
      <div className="mt-3">
        <FormError message={localError ?? serverError} />
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          disabled={add.isPending}
          className="h-8 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {add.isPending ? "Adding" : "Add source"}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="h-8 rounded border border-border-strong px-4 text-sm text-text hover:bg-surface-head"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
