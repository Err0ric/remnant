import { useMutation } from "@tanstack/react-query";
import { Field } from "@/features/auth/Field";
import { OptionalSection } from "@/components/forms/OptionalSection";
import { ApiCredentialsFields } from "./ApiCredentialsFields";
import {
  ApiError,
  api,
  type AnthropicFeed,
  type AnthropicSettings,
  type ApiCredentials,
  type M365ContentType,
  type M365GraphFeed,
  type M365Settings,
} from "@/lib/api";

export const M365_DEFAULTS: M365Settings = {
  tenant_id: "",
  client_id: "",
  cloud: "commercial",
  auth: "certificate",
  content_types: [
    "Audit.AzureActiveDirectory",
    "Audit.Exchange",
    "Audit.SharePoint",
    "Audit.General",
  ],
  graph: ["signins", "directory_audits"],
  // The audit API keeps 7 days; read all of it on first run (install finding F43).
  backfill_hours: 168,
};

/** "ok" is Works; "ok: note" is Works with the note (for example, no subscription yet). */
export function feedResult(result: string): string {
  if (result === "ok") return "Works";
  if (result.startsWith("ok: ")) {
    const note = result.slice(4);
    return `Works. ${note.charAt(0).toUpperCase()}${note.slice(1)}.`;
  }
  return result;
}

export const ANTHROPIC_DEFAULTS: AnthropicSettings = {
  key_type: "admin",
  feeds: ["usage", "cost", "claude_code"],
  backfill_days: 7,
};

export const CONTENT: { id: M365ContentType; label: string; needs: string }[] = [
  { id: "Audit.AzureActiveDirectory", label: "Entra ID audit", needs: "ActivityFeed.Read" },
  { id: "Audit.Exchange", label: "Exchange", needs: "ActivityFeed.Read" },
  { id: "Audit.SharePoint", label: "SharePoint and OneDrive", needs: "ActivityFeed.Read" },
  {
    id: "Audit.General",
    label: "General (Teams, Copilot interactions, and more)",
    needs: "ActivityFeed.Read",
  },
  { id: "DLP.All", label: "DLP rule matches", needs: "ActivityFeed.ReadDlp" },
];
export const GRAPH: { id: M365GraphFeed; label: string; needs: string }[] = [
  { id: "signins", label: "Sign-ins (Entra ID P1 or P2)", needs: "AuditLog.Read.All" },
  { id: "directory_audits", label: "Directory changes", needs: "AuditLog.Read.All" },
  { id: "alerts", label: "Security alerts (Defender, Purview)", needs: "SecurityAlert.Read.All" },
];
export const FEEDS: { id: AnthropicFeed; label: string; needs: string }[] = [
  { id: "usage", label: "API usage by model, workspace, and key (hourly)", needs: "Admin key" },
  { id: "cost", label: "API cost (daily)", needs: "Admin key" },
  { id: "claude_code", label: "Claude Code per person (daily)", needs: "Admin or Analytics key" },
  {
    id: "analytics_users",
    label: "Claude.ai per person (Enterprise, daily)",
    needs: "Analytics key",
  },
  {
    id: "compliance_activities",
    label: "Audit activity: keys, members, settings",
    needs: "Compliance key",
  },
];

function toggle<T>(list: T[], item: T, on: boolean): T[] {
  return on ? [...list.filter((x) => x !== item), item] : list.filter((x) => x !== item);
}

interface ChecklistProps<T extends string> {
  legend: string;
  items: { id: T; label: string; needs: string }[];
  value: T[];
  onChange: (next: T[]) => void;
}

export function Checklist<T extends string>({ legend, items, value, onChange }: ChecklistProps<T>) {
  return (
    <fieldset className="flex flex-col gap-1">
      <legend className="mb-1 text-sm font-semibold">{legend}</legend>
      {items.map((it) => (
        <label key={it.id} className="flex items-baseline gap-2 text-sm">
          <input
            type="checkbox"
            checked={value.includes(it.id)}
            onChange={(e) => onChange(toggle(value, it.id, e.target.checked))}
          />
          <span>
            {it.label} <span className="font-mono text-text-muted">{it.needs}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

const SELECT = "h-9 rounded border border-border-strong bg-inset px-2 text-sm text-text";
const CLOUD_LABEL: Record<M365Settings["cloud"], string> = {
  commercial: "Commercial",
  gcc: "GCC",
  gcc_high: "GCC High",
};

interface ApiSourceFieldsProps {
  /** required: what must be filled in; optional: settings with defaults; test: the
   * connection test, shown after both so it uses the final settings. */
  part: "required" | "optional" | "test";
  kind: "m365" | "anthropic";
  m365: M365Settings;
  anthropic: AnthropicSettings;
  credentials: ApiCredentials;
  onM365: (next: M365Settings) => void;
  onAnthropic: (next: AnthropicSettings) => void;
  onCredentials: (next: ApiCredentials) => void;
}

const FEED_LABEL: Record<string, string> = Object.fromEntries(
  [...CONTENT, ...GRAPH, ...FEEDS].map((f) => [f.id, f.label.split(" (")[0] ?? f.label]),
);

/** Settings for a Microsoft 365 or Anthropic source, with a test before saving. */
export function ApiSourceFields(props: ApiSourceFieldsProps) {
  const { part, kind, m365, anthropic, credentials } = props;
  const test = useMutation({
    mutationFn: () =>
      api.testApiSource(
        kind === "m365" ? { kind, m365, credentials } : { kind, anthropic, credentials },
      ),
  });
  const setM = <K extends keyof M365Settings>(key: K, v: M365Settings[K]) =>
    props.onM365({ ...m365, [key]: v });
  const setA = <K extends keyof AnthropicSettings>(key: K, v: AnthropicSettings[K]) =>
    props.onAnthropic({ ...anthropic, [key]: v });
  const ready =
    kind === "m365"
      ? Boolean(m365.tenant_id && m365.client_id)
      : Boolean(credentials.api_key && anthropic.feeds.length);

  if (part === "required") {
    return kind === "m365" ? (
      <>
        <Field
          label="Directory (tenant) ID"
          help="From the app registration's Overview page."
          value={m365.tenant_id}
          onChange={(e) => setM("tenant_id", e.target.value.trim())}
          className="font-mono"
          required
        />
        <Field
          label="Application (client) ID"
          value={m365.client_id}
          onChange={(e) => setM("client_id", e.target.value.trim())}
          className="font-mono"
          required
        />
        <div className="flex flex-col gap-1">
          <label htmlFor="m365-auth" className="text-sm font-semibold">
            Sign in with
          </label>
          <select
            id="m365-auth"
            value={m365.auth}
            onChange={(e) => {
              setM("auth", e.target.value as M365Settings["auth"]);
              props.onCredentials({});
            }}
            className={SELECT}
          >
            <option value="certificate">Certificate (recommended)</option>
            <option value="secret">Client secret</option>
          </select>
        </div>
        <ApiCredentialsFields
          kind="m365"
          auth={m365.auth}
          value={credentials}
          onChange={props.onCredentials}
        />
      </>
    ) : (
      <ApiCredentialsFields kind="anthropic" value={credentials} onChange={props.onCredentials} />
    );
  }

  if (part === "optional") {
    const feeds =
      kind === "m365" ? [...m365.content_types, ...m365.graph] : (anthropic.feeds as string[]);
    const summary = [
      kind === "m365" ? `Cloud: ${CLOUD_LABEL[m365.cloud]}` : `Key type: ${anthropic.key_type}`,
      `Feeds: ${feeds.map((f) => FEED_LABEL[f] ?? f).join(", ") || "none"}`,
      kind === "m365"
        ? `First run reads ${m365.backfill_hours} h`
        : `First run reads ${anthropic.backfill_days} days`,
    ].join(" · ");
    return (
      <OptionalSection title="Cloud, feeds, and history" summary={summary}>
        {kind === "m365" ? (
          <>
            <div className="flex flex-col gap-1">
              <label htmlFor="m365-cloud" className="text-sm font-semibold">
                Cloud
              </label>
              <select
                id="m365-cloud"
                value={m365.cloud}
                onChange={(e) => setM("cloud", e.target.value as M365Settings["cloud"])}
                className={SELECT}
              >
                <option value="commercial">Commercial</option>
                <option value="gcc">GCC</option>
                <option value="gcc_high">GCC High</option>
              </select>
            </div>
            <Field
              label="On first run, read back (hours)"
              help="At most 168 (7 days, all the audit API keeps). A busy tenant's 7 days can be hundreds of thousands of events; the first run catches up over a few polls."
              type="number"
              min={0}
              max={168}
              value={m365.backfill_hours}
              onChange={(e) => setM("backfill_hours", Number(e.target.value))}
            />
            <Checklist
              legend="Audit logs (Office 365 Management APIs)"
              items={CONTENT}
              value={m365.content_types}
              onChange={(v) => setM("content_types", v)}
            />
            <Checklist
              legend="Microsoft Graph"
              items={GRAPH}
              value={m365.graph}
              onChange={(v) => setM("graph", v)}
            />
          </>
        ) : (
          <>
            <div className="flex flex-col gap-1">
              <label htmlFor="anthropic-key-type" className="text-sm font-semibold">
                Key type
              </label>
              <select
                id="anthropic-key-type"
                value={anthropic.key_type}
                onChange={(e) => setA("key_type", e.target.value as AnthropicSettings["key_type"])}
                className={SELECT}
              >
                <option value="admin">Admin key</option>
                <option value="analytics">Analytics key</option>
                <option value="compliance">Compliance key</option>
              </select>
            </div>
            <Field
              label="On first run, read back (days)"
              type="number"
              min={0}
              max={31}
              value={anthropic.backfill_days}
              onChange={(e) => setA("backfill_days", Number(e.target.value))}
            />
            <Checklist
              legend="Feeds"
              items={FEEDS}
              value={anthropic.feeds}
              onChange={(v) => setA("feeds", v)}
            />
          </>
        )}
      </OptionalSection>
    );
  }

  return (
    <div className="flex flex-col gap-2 md:col-span-2">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => test.mutate()}
          disabled={test.isPending || !ready}
          className="h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head disabled:opacity-50"
        >
          {test.isPending ? "Testing…" : "Test connection"}
        </button>
        <span className="text-sm text-text-muted">One small read per selected feed</span>
      </div>
      {test.error ? (
        <p role="alert" className="text-sm text-danger">
          {test.error instanceof ApiError ? test.error.message : "The test did not work"}
        </p>
      ) : null}
      {test.data ? (
        <div role="status" className="flex flex-col gap-1 text-sm">
          {test.data.thumbprint ? (
            <p className="text-text-secondary">
              Certificate thumbprint{" "}
              <span className="font-mono text-text">{test.data.thumbprint}</span>: it should match
              the one Entra shows.
            </p>
          ) : null}
          <ul className="flex flex-col gap-0.5">
            {Object.entries(test.data.feeds).map(([feed, result]) => (
              <li key={feed} className="flex flex-wrap gap-2">
                <span className="font-mono">{feed}</span>
                <span className={result.startsWith("ok") ? "text-ok" : "text-warn"}>
                  {feedResult(result)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
