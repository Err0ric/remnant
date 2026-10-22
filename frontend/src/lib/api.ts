import { reportReached, reportUnreachable, unreachableStatus } from "@/lib/connectivity";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// Session CSRF token, set by the auth gate after sign-in. Sent on every write.
let csrfToken: string | null = null;
let onAuthLost: (() => void) | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

/** Called when the server says the session is gone, so the app can show sign-in. */
export function setAuthLostHandler(handler: (() => void) | null) {
  onAuthLost = handler;
}

async function request<T>(path: string, init?: RequestInit, asText = false): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let res: Response;
  try {
    res = await fetch(path, { ...init, credentials: "same-origin", headers });
  } catch (err) {
    reportUnreachable(); // the request never reached the server (F40)
    throw err;
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    let code: string | undefined;
    try {
      const body = (await res.json()) as { detail?: unknown; code?: string };
      if (typeof body.detail === "string") detail = body.detail;
      code = body.code;
    } catch {
      // Non-JSON error body: keep the status line.
    }
    if (unreachableStatus(res.status, code)) reportUnreachable();
    else reportReached();
    if (code === "auth_required" || code === "setup_required") onAuthLost?.();
    throw new ApiError(res.status, detail, code);
  }
  reportReached();
  if (res.status === 204) return undefined as T;
  if (asText) return (await res.text()) as T;
  return (await res.json()) as T;
}

/** The read-only MCP server's settings (ADR-0003). */
export interface McpSettings {
  enabled: boolean;
  endpoint_local: boolean;
  updated_at: string | null;
  path: string;
}

export interface Meta {
  product_name: string;
  version: string;
  ocsf_version: string;
  schema_version: number;
  environment_label?: string | null;
}

export interface Health {
  status: string;
}

export interface QueryRequest {
  sql: string;
  start?: string;
  end?: string;
  sources?: string[];
  /** Values for $name placeholders, bound by the server (Simple search sends these). */
  params?: Record<string, string | number | boolean | null>;
}

/** POST /api/search/compile (ADR-0009): Simple search text as SQL plus parameters. */
/** POST /api/search/facets (ADR-0016): top values per field for the search on screen. */
export interface FacetRequest {
  text?: string;
  sql?: string;
  params?: Record<string, string | number | boolean | null>;
  columns?: string[];
  start?: string;
  sources?: string[];
}

export interface Facet {
  field: string;
  values: { value: string | null; count: number }[];
}

/** AI usage (ADR-0015). */
export type AiStatus = "approved" | "not_approved" | "unreviewed";

export interface AiService {
  id: string;
  name: string;
  vendor: string;
  kind: string;
  domains: string[];
  status: AiStatus;
  custom: boolean;
  note: string;
  /** The most sensitive data allowed to the service (ADR-0020 row 4). */
  data_level?: DataLevel | null;
}

export interface AiServiceUse {
  service: AiService;
  events: number;
  people: number;
  machines: number;
  first_seen: string | null;
  last_seen: string | null;
  top_people: string[];
  top_machines: string[];
}

export interface AiMcpUse {
  name: string;
  status: AiStatus;
  calls: number;
  people: number;
  machines: number;
  installs: number;
  clients: string[];
  first_seen: string | null;
  last_seen: string | null;
  sources: string[];
}

export interface AiPerson {
  person: string;
  /** Null only if stored data was bad; the page shows "·" then. */
  cost_usd: number | null;
  tokens: number;
  sessions: number;
  tool_calls: number;
  errors: number;
  sensitive: number;
  models: string[];
}

export interface AiGone {
  kind: "service" | "mcp";
  id: string;
  name: string;
  status: AiStatus;
  last_seen: string | null;
}

export interface AiUsage {
  services: AiServiceUse[];
  /** Vendor hosts other sites load (ad and measurement tags): shown apart, not AI use. */
  non_usage?: AiServiceUse[];
  mcp: AiMcpUse[];
  people: AiPerson[];
  sources_in_scope: string[];
  /** Start of the period of the same length before the range; null for all time. */
  compared_from: string | null;
  new_services: string[];
  new_mcp: string[];
  /** Seen in that earlier period and not in the range. */
  gone: AiGone[];
}

export interface AiMcpRule {
  pattern: string;
  status: "approved" | "not_approved";
  note: string;
  updated_at: string;
  updated_by: string | null;
}

export interface AiWatch {
  enabled: boolean;
  include_unreviewed: boolean;
  sensitive: boolean;
  target_ids: string[];
  updated_at: string | null;
  updated_by: string | null;
  /** Alert when an AI agent changes (ADR-0020 row 3). */
  agents?: boolean;
}

export interface SearchPreset {
  id: string;
  name: string;
  description: string;
  text: string;
}

export interface CompiledSearch {
  sql: string;
  params: Record<string, string | number | boolean | null>;
  notes: string[];
  /** Schema columns the search filters on (so the UI can say when one is empty). */
  columns?: string[];
}

export type Cell = string | number | boolean | null | Record<string, unknown> | unknown[];

export interface GeoInfo {
  country: string | null;
  country_name: string | null;
  asn: number | null;
  org: string | null;
}

export interface QueryResult {
  columns: string[];
  rows: Cell[][];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
  executed_sql: string;
  sources: string[];
  /** Public addresses in the rows, from the local GeoIP files; absent on older servers. */
  geo?: Record<string, GeoInfo>;
  /** Values in the rows listed in an enabled threat intel list (ADR-0023 row 7). */
  intel?: Record<string, IntelHit[]>;
}

export interface IntelHit {
  feed: string;
  type: string;
  threat: string;
  last_seen: string | null;
}

export type FeedLevel = "healthy" | "attention" | "unhealthy" | "missing";

export interface EnrichmentFeed {
  feed_id: string;
  kind: "geoip" | "intel";
  enabled: boolean;
  needs_key: boolean;
  has_key: boolean;
  downloadable: boolean;
  label: string;
  provider: string;
  terms_url: string;
  level: FeedLevel;
  version: string | null;
  entries: number;
  size: number;
  source: "download" | "upload" | null;
  installed_at: string | null;
  checked_at: string | null;
  error: string | null;
  check_every_s: number;
}

export interface EnrichmentStatus {
  auto_update: boolean;
  feeds: EnrichmentFeed[];
  attribution: string;
  attribution_url: string;
}

export type AuthMode = "open" | "setup" | "login";

export interface User {
  user_id: string;
  username: string;
  role: "admin" | "analyst" | "auditor";
}

/** Single sign-on, when the server has it turned on (ADR-0013). */
export interface SsoState {
  /** Button text, for example "Microsoft". */
  label: string;
  /** With SSO on, only administrators may use a password. */
  passwords_admins_only: boolean;
}

export interface AuthState {
  mode: AuthMode;
  user: User | null;
  csrf_token: string | null;
  sso?: SsoState | null;
}

export interface SignedIn {
  user: User;
  csrf_token?: string;
}

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export type SourceFormat = "syslog" | "json" | "csv";

/** A Grafana Loki source's settings (ADR-0011). The password or token is sent apart. */
export interface LokiSettings {
  url: string;
  query: string;
  tenant?: string | null;
  auth: "none" | "basic" | "bearer";
  username?: string | null;
  backfill_hours: number;
}

export interface LokiStreamGroup {
  labels: Record<string, string>;
  streams: number;
}

export interface LokiTestResult {
  lines: number;
  stream_count: number;
  /** Label sets with per-id labels (proc_id, pid) left out, largest first. */
  groups: LokiStreamGroup[];
  ignored_labels: string[];
  newest: string | null;
}

export type M365ContentType =
  | "Audit.AzureActiveDirectory"
  | "Audit.Exchange"
  | "Audit.SharePoint"
  | "Audit.General"
  | "DLP.All";
export type M365GraphFeed = "signins" | "directory_audits" | "alerts";

/** Microsoft 365 connector settings (ADR-0002). */
export interface M365Settings {
  tenant_id: string;
  client_id: string;
  cloud: "commercial" | "gcc" | "gcc_high";
  auth: "certificate" | "secret";
  content_types: M365ContentType[];
  graph: M365GraphFeed[];
  backfill_hours: number;
}

export type AnthropicFeed =
  "usage" | "cost" | "claude_code" | "analytics_users" | "compliance_activities";

/** Anthropic Admin API connector settings (ADR-0015 row 10). */
export interface AnthropicSettings {
  key_type: "admin" | "analytics" | "compliance";
  feeds: AnthropicFeed[];
  backfill_days: number;
}

/** Write-only credentials for an API source; stored encrypted, never returned. */
export interface ApiCredentials {
  api_key?: string;
  client_secret?: string;
  certificate_pem?: string;
  private_key_pem?: string;
}

export interface ApiTestResult {
  /** Feed name to "ok" or why it failed. */
  feeds: Record<string, string>;
  /** Microsoft 365 certificates: the thumbprint Entra shows. */
  thumbprint: string | null;
}

/** Entity risk (ADR-0016 row 4): the score and its parts. */
export interface EntityRisk {
  kind: "user" | "ip" | "host";
  value: string;
  score: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
  flagged_runs: number;
  events: number;
  rules: string[];
  search_sql: string;
  /** Users: the logged names counted as this person. */
  names?: string[];
}

export interface RiskResponse {
  users: EntityRisk[];
  ips: EntityRisk[];
  hosts: EntityRisk[];
  matches_considered: number;
  sources: string[];
}

export interface GraphCard {
  id: string;
  lane: number;
  label: string;
  sublabel: string;
  events: number;
  matches: number;
  max_severity: number;
  badges: string[];
  search_sql: string | null;
  /** A heading inside the lane ("MCP servers"); empty for none. */
  group: string;
}

/** Investigator lanes (ADR-0016 row 5). */
export interface EntityGraph {
  mode: "entity" | "ai";
  lanes: string[];
  cards: GraphCard[];
  edges: { source: string; target: string; events: number }[];
  more: number[];
  sources: string[];
}

/** An AI agent and what changed (ADR-0020 rows 2 and 3). */
export interface AiAgent {
  kind: string;
  agent: string;
  label: string;
  owners: string[];
  machine: string | null;
  first_seen: string;
  last_seen: string;
  events_24h: number;
  state: "new" | "changed" | "usual";
  new_items: { kind: string; name: string }[];
  usual_peak: number | null;
  recent_peak: number | null;
}

export type DataLevel = "public" | "internal" | "confidential";

/** Who had an address at a time (ADR-0020 row 1). */
export interface AddressHolders {
  ip: string;
  at: string;
  max_age_hours: number;
  holders: { kind: "user" | "host"; name: string; last_seen: string; events: number }[];
}

/** Health page (ADR-0019). */
export type HealthState = "healthy" | "attention" | "unhealthy" | "unknown";

export interface WatchedDevice {
  device_id: string;
  name: string;
  /** IP address or host name, lower case. */
  match: string;
  silence_s: number;
  /** Administrators only; empty for others. */
  target_ids: string[];
  state: HealthState;
  reason: string | null;
  last_seen: string | null;
  /** Events per hour, oldest first, 24 values. */
  hourly: number[];
}

export interface AgentHealth {
  kind: string;
  source_id: string;
  machine: string;
  last_seen: string | null;
  events_24h: number;
  state: HealthState;
  reason: string | null;
}

export interface IntegrityFinding {
  severity: "failure" | "warning";
  kind: string;
  path: string;
  detail: string;
}

export interface IntegritySeal {
  seal_id: number;
  at: string;
  status: "verified" | "warnings" | "failed";
  lake_head: string;
  lake_seq: number;
  audit_head: string;
  audit_rows: number;
  /** Chain head of AI call records; empty on seals made before they were chained. */
  llm_head: string;
  llm_rows: number;
  files: number;
  failures: number;
  warnings: number;
  findings: IntegrityFinding[];
  signature: string;
  signature_ok: boolean;
}

export interface IntegritySettings {
  target_ids: string[];
  send_seals: boolean;
  updated_at: string | null;
}

export interface IntegrityStatus {
  latest: IntegritySeal | null;
  history: IntegritySeal[];
  lake_head: string;
  lake_entries: number;
  interval_s: number;
  settings: IntegritySettings;
}

export interface HealthChecks {
  devices: WatchedDevice[];
  agents: AgentHealth[];
  /** Damaged lake files moved to data/quarantine (SPEC D51). */
  quarantined_files?: number;
}

export interface WatchedDeviceInput {
  name: string;
  match: string;
  silence_s: number;
  target_ids: string[];
}

/** One person under several names (ADR-0018). */
export interface IdentityAlias {
  alias: string;
  person: string;
  created_by: string | null;
  created_at: string;
}

export interface Identities {
  domains: string[];
  aliases: IdentityAlias[];
  domain_suggestions: { domain: string; addresses: number; shared: number; examples: string[] }[];
  alias_suggestions: { alias: string; person: string; hosts: string[] }[];
}

export type GraphKind = "user" | "ip" | "host" | "mcp" | "service";

export type SourceKind = "file" | "loki" | "otlp" | "m365" | "anthropic" | "syslog";

/** A syslog listener source's socket (ADR-0021). */
export interface SyslogSettings {
  protocol: "udp" | "tcp" | "tls";
  port: number;
  /** Addresses or networks; empty means private, loopback, and link-local only. */
  allowed_senders: string[];
}

export interface ListenerSender {
  address: string;
  count: number;
  last_seen: string | null;
  allowed: boolean;
}

export interface ListenerStatus {
  protocol: string;
  port: number;
  listening: boolean;
  received: number;
  dropped_not_allowed: number;
  dropped_full: number;
  connections: number;
  last_message_at: string | null;
  /** Administrators only; empty for other viewers. */
  senders: ListenerSender[];
}

export interface SourceInput {
  source_id: string;
  format: SourceFormat;
  /** file (default), loki, otlp (pushed to the OTLP receiver), m365, or anthropic. */
  kind?: SourceKind;
  loki?: LokiSettings | null;
  m365?: M365Settings | null;
  anthropic?: AnthropicSettings | null;
  syslog?: SyslogSettings | null;
  /** Write-only, for m365 and anthropic sources. */
  credentials?: ApiCredentials;
  /** Write-only: a Loki password or token, stored encrypted. */
  loki_secret?: string;
  path: string;
  glob: string;
  timezone: string;
  retention_days: number;
  /** Parse with this template; "auto" picks one per line; null uses the generic parser. */
  template_id?: string | null;
}

export interface TemplateInfo {
  id: string;
  name: string;
  version: string;
  description: string;
  category: string;
  envelope: "syslog" | "none";
  payload_format: string;
  class_uid: number;
  classification_default: "local_only" | "cloud_allowed";
}

export interface TemplateMatch {
  template_id: string;
  name: string;
  /** Share of sampled lines the template's match rules accept. */
  confidence: number;
  min_confidence: number;
  passes: boolean;
  /** Share of sampled lines parsed fully or partly. */
  parse_rate: number;
  /** OCSF columns filled per line, on average. */
  coverage: number;
}

export interface DiscoveryCandidate {
  path: string;
  glob: string;
  files: number;
  bytes: number;
  hosts: string[];
  kind: "text" | "evtx" | "binary";
  sniff: {
    lines: number;
    envelope: Record<string, number>;
    app_names: [string, number][];
    formats: Record<string, number>;
    format: string;
  } | null;
  matches: TemplateMatch[];
  preview: string[];
  /** Files the suggested pattern reaches beyond this candidate's own. */
  extra_matches: number;
}

export interface DiscoveryReport {
  root: string;
  candidates: DiscoveryCandidate[];
  skipped: Record<string, number>;
  truncated: boolean;
}

export interface DraftSampleInput {
  kind: "file" | "pasted" | "none";
  path?: string;
  glob?: string;
  text?: string;
}

export interface DraftInfo {
  template_id: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  sample: {
    kind: "file" | "pasted" | "none";
    path: string | null;
    glob: string | null;
    lines: number;
  };
  llm_call_id: string | null;
  /** Version of the approved template this draft would replace, if any. */
  replaces_version: string | null;
}

export interface Draft extends DraftInfo {
  yaml: string;
}

export interface DraftPreview {
  valid: boolean;
  errors: string[];
  tests: { name: string; passed: boolean; problems: string[] }[];
  lines: number;
  ok: number;
  partial: number;
  failed: number;
  rows: {
    line: number;
    raw: string;
    parse_status: string;
    parse_errors: string | null;
    class_uid: number | null;
    fields: Record<string, string | number | boolean | null>;
  }[];
  approvable: boolean;
  /** sha256 of exactly the YAML these results describe. */
  sha256: string;
}

export interface TemplateApproval {
  approval_id: string;
  template_id: string;
  version: string;
  sha256: string;
  approved_by: string;
  approved_at: string;
}

export interface SourceStatus {
  state: "waiting" | "reading" | "error" | "disabled";
  files: number;
  last_pass_at: string | null;
  last_event_at: string | null;
  events_since_start: number;
  error: string | null;
  /** EVTX records that could not be read, from the latest read of each file. */
  records_skipped: number;
  /** .evtx files shorter than their header says, waiting for their size to settle. */
  files_waiting: number;
  /** Loki and API sources: how far reading is behind now, in seconds. */
  behind_s?: number | null;
  /** API sources: feeds that failed while the others worked. */
  warnings?: string[];
  /** API sources: when the next try is, after errors. */
  retry_at?: string | null;
  /** Syslog listener sources: the socket and who is sending (ADR-0021). */
  listener?: ListenerStatus | null;
  /** Event times steadily this many hours off (positive: early): check the time zone. */
  time_offset_h?: number | null;
  time_offset_text?: string | null;
}

/** Quiet-source alert state (ADR-0014); null when no alert is set. */
export interface SourceQuiet {
  quiet_after_s: number;
  state: "ok" | "quiet";
  quiet_since: string | null;
  last_seen: string | null;
}

/** Admin view of a quiet-source alert, with its targets. */
export interface SourceWatch extends SourceQuiet {
  source_id: string;
  target_ids: string[];
  updated_at: string;
  updated_by: string | null;
}

export interface Source extends SourceInput {
  /** OTLP sources: prompt and tool content kept instead of dropped (ADR-0015 row 4). */
  otlp_keep_content?: boolean;
  classification: "local_only" | "cloud_allowed";
  enabled: boolean;
  status: SourceStatus;
  quiet?: SourceQuiet | null;
}

export interface ColumnInfo {
  name: string;
  type: string;
  group: string;
  description: string;
  nullable: boolean;
}

export type Role = "admin" | "analyst" | "auditor";

export interface ManagedUser {
  user_id: string;
  username: string;
  role: Role;
  disabled: boolean;
  pending: boolean;
  created_at: string;
  last_login_at: string | null;
  /** Signs in with single sign-on. */
  sso?: boolean;
}

/** A group suggested from template categories or vendors (SPEC 3.6). Never applied on its own. */
export interface GroupSuggestion {
  kind: "category" | "vendor";
  key: string;
  name: string;
  group_id: string | null;
  source_ids: string[];
  missing: string[];
}

export interface SourceGroup {
  group_id: string;
  name: string;
  description: string;
  source_ids: string[];
  user_ids: string[];
}

const put = (body: unknown): RequestInit => ({ method: "PUT", body: JSON.stringify(body) });
const patch = (body: unknown): RequestInit => ({ method: "PATCH", body: JSON.stringify(body) });

export interface ApiToken {
  token_id: string;
  label: string;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
}

export type ParamType = "int" | "float" | "string" | "bool" | "timestamp";

export interface ParamDef {
  name: string;
  type: ParamType;
  default?: string | number | boolean | null;
  description?: string;
}

export interface SavedSearchInput {
  id: string;
  name: string;
  description: string;
  tags: string[];
  visibility: "private" | "shared";
  sources?: string[] | null;
  sql: string;
  params: ParamDef[];
  mode?: "query" | "ask";
  /** Informational: the Ask question that produced the SQL. */
  origin?: Record<string, string> | null;
}

export interface SavedSearch extends SavedSearchInput {
  owner_id: string;
  verified: boolean;
  created_at: string;
  updated_at: string;
}

/** Upload a YAML document (saved-search import) with the session's CSRF token. */
async function postYaml<T>(path: string, text: string): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/yaml",
  };
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers,
    body: text,
  });
  const body = (await res.json().catch(() => ({}))) as { detail?: string; code?: string };
  if (!res.ok) throw new ApiError(res.status, body.detail ?? `${res.status}`, body.code);
  return body as T;
}

async function requestText(path: string): Promise<string> {
  const res = await fetch(path, { credentials: "same-origin" });
  if (!res.ok) throw new ApiError(res.status, `${res.status} ${res.statusText}`);
  return res.text();
}

export interface AskProvider {
  provider_id: string;
  name: string;
  model: string;
  locality: "local" | "cloud";
}

export interface ProviderConfig {
  provider_id: string;
  name: string;
  kind: string;
  base_url: string;
  model: string;
  enabled: boolean;
  has_api_key: boolean;
  locality: "local" | "cloud";
  /** False when the host did not resolve, which is why it counts as cloud. */
  host_found: boolean;
  /** Opt-in (ADR-0010): IPs, users, and hosts sent as tokens to this cloud provider. */
  redact: boolean;
  /** Thinking control sent as reasoning_effort; null: the model's default. */
  reasoning: "none" | "low" | "medium" | "high" | null;
  /** ADR-0028: requests sent at once (null: 1 for local, no limit for cloud). */
  max_concurrent: number | null;
  /** Seconds a request waits for the model before "busy" (null: 120). */
  wait_budget_s: number | null;
  effective_slots: number | null;
  effective_wait_s: number;
}

export interface ProviderInput {
  name?: string;
  redact?: boolean;
  reasoning?: "none" | "low" | "medium" | "high" | "default";
  /** On create only: openai_compat (default) or anthropic, which is always cloud. */
  kind?: "openai_compat" | "anthropic";
  base_url?: string;
  model?: string;
  enabled?: boolean;
  api_key?: string;
  clear_api_key?: boolean;
  acknowledge_cloud?: boolean;
  /** 0 returns to the default. */
  max_concurrent?: number;
  wait_budget_s?: number;
}

/** How busy a provider is now (ADR-0028): counts only. */
export interface ProviderQueue {
  slots: number | null;
  running: number;
  waiting: number;
}

export interface ProviderHealth {
  ok: boolean;
  /** Answering another request: occupied, not down. */
  busy?: boolean;
  detail: string;
  models: string[];
}

export interface AskTurn {
  question: string;
  sql: string;
}

export interface AskRequest {
  question: string;
  provider_id?: string;
  start?: string;
  sources?: string[];
  history: AskTurn[];
}

export interface AskResponse {
  sql: string;
  explanation: string;
  assumptions: string[];
  check: "ok" | "empty" | "failed";
  check_detail: string | null;
  attempts: number;
  provider: AskProvider;
  call_ids: string[];
}

export interface SigmaRule {
  rule_id: string;
  title: string;
  /** "" when the rule names none; shown as "author not stated" (DRL 1.1). */
  author: string;
  level: string;
  status: string;
  product: string | null;
  service: string | null;
  category: string | null;
  tags: string[];
  path: string;
  enabled: boolean;
  sha256: string;
  import_id: string;
  updated_at: string;
}

/** As listed: plus the sources a run would read for this caller (empty: no data). */
export interface SigmaRuleListed extends SigmaRule {
  source_ids: string[];
}

export interface SigmaRuleDetail extends SigmaRule {
  yaml: string;
}

export interface RuleRefusal {
  path: string;
  reason: string;
}

export interface RuleImportReport {
  import_id: string;
  path: string;
  files: number;
  accepted: number;
  new_rules: number;
  updated: number;
  unchanged: number;
  refused: number;
  truncated: boolean;
  refusals: RuleRefusal[];
}

export interface RuleRun {
  run_id: string;
  rule_id: string;
  sha256: string;
  title: string;
  author: string;
  level: string;
  started_by: string;
  started_at: string;
  range_start: string;
  range_end: string;
  status: "ok" | "no_data" | "failed";
  match_count: number;
  matches_stored: number;
  elapsed_ms: number;
  sources_in_scope: string[];
  error: string | null;
}

export interface RuleMatch {
  event_id: string;
  event_time: string | null;
  source_id: string;
}

export type ThresholdKind = "above" | "below" | "change_pct";

export interface ScheduleRunSummary {
  run_id: string;
  started_at: string;
  range_start: string | null;
  range_end: string | null;
  status: "ok" | "failed" | "paused";
  /** The viewer may not read every source this run read: no numbers or rows are shown. */
  restricted: boolean;
  row_count: number | null;
  elapsed_ms: number | null;
  sources_in_scope: string[];
  flagged: boolean;
  flag_reason: string | null;
  error: string | null;
  rule_run_id: string | null;
  /** A drop to zero right after a source this run read changed parser (F36). */
  parser_change?: string | null;
  /** The first run after the schedule's definition changed says what changed (F37). */
  definition_change?: string | null;
}

export interface ScheduleRunDetail extends ScheduleRunSummary {
  columns: string[];
  sample: Cell[][];
  truncated: boolean;
}

/** GET /api/overview (ADR-0008): read as the viewer, cached for a minute server side. */
export interface OverviewSourceHealth {
  source_id: string;
  state: SourceStatus["state"];
  last_event_at: string | null;
  files_waiting: number;
  records_skipped: number;
  error: string | null;
  /** Set while the source's quiet-source alert is firing (ADR-0014). */
  quiet_since?: string | null;
}

export interface OverviewDetection {
  kind: "rule" | "search";
  name: string;
  level: string | null;
  count: number;
  reason: string | null;
  started_at: string;
  run_id: string;
  schedule_id: string | null;
}

export interface OverviewTargetHealth {
  target_id: string;
  name: string;
  kind: string;
  consecutive_failures: number;
  failing: boolean;
  last_error: string | null;
}

export interface Overview {
  generated_at: string;
  hours: string[];
  volume: {
    source_id: string;
    counts: number[];
    /** Median of the same hour on up to 7 earlier days; null before 3 days of history. */
    typical: (number | null)[];
    marks: ("" | "busy" | "quiet")[];
  }[];
  sources: OverviewSourceHealth[];
  detections: OverviewDetection[];
  paused: { schedule_id: string; name: string; kind: string; reason: string | null }[];
  alerts: { targets: OverviewTargetHealth[]; failed_deliveries: number } | null;
}

/** GET /api/audit/... (Slice 5): admins and auditors only; reading is itself audited. */
export interface AuditFilters {
  action?: string;
  user_id?: string;
  outcome?: "success" | "failure" | "denied" | "blocked";
  since?: string;
  until?: string;
}

export interface AuditEvent {
  audit_id: number;
  ts: string;
  user_id: string | null;
  username: string | null;
  action: string;
  outcome: "success" | "failure" | "denied";
  ip: string | null;
  detail: Record<string, unknown>;
}

export interface AuditLlmCall {
  call_id: string;
  ts: string;
  user_id: string;
  username: string | null;
  provider_id: string;
  model: string;
  locality: "local" | "cloud";
  purpose: string;
  prompt_ref: string;
  sources_in_scope: string[];
  classification_result: "allowed" | "blocked";
  redaction_applied: boolean;
  redaction_counts: Record<string, number> | null;
  prompt_sha256: string | null;
  response_sha256: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  latency_ms: number | null;
  /** ADR-0028: time waiting for a free slot, and busy answers retried. */
  queue_wait_ms?: number | null;
  busy_retries?: number | null;
  citation_check: "pass" | "fail" | null;
  error: string | null;
  finished_at: string | null;
  /** Null once the provider was deleted. */
  provider_name?: string | null;
  /** Integrity chain hash, set when the call completed (D61). */
  chain_hash?: string | null;
}

function queryString(values: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(values)) if (v !== undefined && v !== "") q.set(k, String(v));
  const text = q.toString();
  return text ? `?${text}` : "";
}

export interface Schedule {
  schedule_id: string;
  kind: "search" | "rule";
  target_id: string;
  name: string;
  owner_id: string;
  mine: boolean;
  shared: boolean;
  cron: string;
  lookback_minutes: number | null;
  params: Record<string, string | number | boolean>;
  threshold_kind: ThresholdKind | null;
  threshold_value: number | null;
  paused: boolean;
  paused_reason: string | null;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
  /** Newest first, up to 30. */
  recent: ScheduleRunSummary[];
  target_ids: string[];
  /** Dashboard panel width and view, set by the owner or an admin. */
  panel_width?: "third" | "half" | "full";
  panel_view?: "table" | "bars";
}

export interface ScheduleInput {
  kind: "search" | "rule";
  target_id: string;
  name?: string;
  cron: string;
  lookback_minutes?: number | null;
  shared?: boolean;
  threshold_kind?: ThresholdKind | null;
  threshold_value?: number | null;
  target_ids?: string[];
}

export interface ScheduleUpdate {
  name?: string;
  cron?: string;
  shared?: boolean;
  paused?: boolean;
  target_ids?: string[];
  panel_width?: "third" | "half" | "full";
  panel_view?: "table" | "bars";
  /** 0 clears the range (since the last run). */
  lookback_minutes?: number;
  /** "none" clears the threshold. */
  threshold_kind?: ThresholdKind | "none";
  threshold_value?: number;
  /** A new definition (F37): history is kept and the next run notes the change. */
  kind?: "search" | "rule";
  target_id?: string;
  params?: Record<string, string | number | boolean>;
}

export interface ExplainClaim {
  text: string;
  event_ids: string[];
  /** Cites at least one event, and only events that were sent. */
  verified: boolean;
}

export interface ExplainResponse {
  claims: ExplainClaim[];
  citation_check: "pass" | "fail";
  call_id: string;
  events_sent: string[];
  not_found: number;
  sources: string[];
  provider: AskProvider;
}

export type AlertTargetKind = "email" | "slack" | "teams" | "webhook";

export interface EmailSettings {
  host: string;
  port: number;
  security: "starttls" | "tls" | "none";
  username?: string | null;
  from_addr: string;
  to_addrs: string[];
}

export interface AlertTarget {
  target_id: string;
  name: string;
  kind: AlertTargetKind;
  /** Host only, for recognition; never the URL or its token. */
  display: string;
  recipients: string[];
  failing: boolean;
  consecutive_failures: number;
  last_error: string | null;
  last_sent_at: string | null;
}

export interface AlertTargetInput {
  name: string;
  kind: AlertTargetKind;
  url?: string;
  email?: EmailSettings;
  password?: string;
}

export interface AlertDelivery {
  delivery_id: string;
  target_name: string | null;
  kind: string;
  status: "pending" | "sent" | "failed";
  attempts: number;
  next_attempt_at: string | null;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
}

export const api = {
  alertTargets: () => request<AlertTarget[]>("/api/alert-targets"),
  createAlertTarget: (body: AlertTargetInput) =>
    request<AlertTarget & { signing_key: string | null }>("/api/alert-targets", post(body)),
  deleteAlertTarget: (id: string) =>
    request<void>(`/api/alert-targets/${encodeURIComponent(id)}`, { method: "DELETE" }),
  testAlertTarget: (id: string) =>
    request<{ ok: boolean; detail: string }>(`/api/alert-targets/${encodeURIComponent(id)}/test`, {
      method: "POST",
    }),
  scheduleDeliveries: (id: string) =>
    request<AlertDelivery[]>(`/api/schedules/${encodeURIComponent(id)}/deliveries`),
  explain: (
    body: { event_ids: string[]; provider_id?: string; question?: string },
    signal?: AbortSignal,
  ) => request<ExplainResponse>("/api/explain", { ...post(body), signal }),
  providerQueue: (id: string) =>
    request<ProviderQueue>(`/api/ask/providers/${encodeURIComponent(id)}/queue`),
  schedules: () => request<Schedule[]>("/api/schedules"),
  overview: () => request<Overview>("/api/overview"),
  auditEvents: (f: AuditFilters, before?: number) =>
    request<AuditEvent[]>(`/api/audit/events${queryString({ ...f, before, limit: 100 })}`),
  auditCalls: (f: AuditFilters, before?: { ts: string; id: string }) =>
    request<AuditLlmCall[]>(
      `/api/audit/llm-calls${queryString({ ...f, before_ts: before?.ts, before_id: before?.id, limit: 100 })}`,
    ),
  /** Server-side CSV of everything matching the filters; the export is audited. */
  auditExport: (log: "events" | "llm-calls", f: AuditFilters) =>
    request<string>(`/api/audit/${log}/export${queryString({ ...f })}`, undefined, true),
  createSchedule: (body: ScheduleInput) => request<Schedule>("/api/schedules", post(body)),
  updateSchedule: (id: string, body: ScheduleUpdate) =>
    request<Schedule>(`/api/schedules/${encodeURIComponent(id)}`, patch(body)),
  deleteSchedule: (id: string) =>
    request<void>(`/api/schedules/${encodeURIComponent(id)}`, { method: "DELETE" }),
  runSchedule: (id: string) =>
    request<ScheduleRunDetail>(`/api/schedules/${encodeURIComponent(id)}/run`, { method: "POST" }),
  scheduleRun: (id: string, runId: string) =>
    request<ScheduleRunDetail>(
      `/api/schedules/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}`,
    ),
  rules: () => request<SigmaRuleListed[]>("/api/rules"),
  rule: (id: string) => request<SigmaRuleDetail>(`/api/rules/${encodeURIComponent(id)}`),
  importRules: (path: string) => request<RuleImportReport>("/api/rules/import", post({ path })),
  setRulesEnabled: (ruleIds: string[], enabled: boolean) =>
    request<{ changed: number }>("/api/rules/enabled", post({ rule_ids: ruleIds, enabled })),
  runRule: (id: string, start: string, end: string) =>
    request<RuleRun>(`/api/rules/${encodeURIComponent(id)}/run`, post({ start, end })),
  ruleRuns: () => request<RuleRun[]>("/api/rules/runs"),
  ruleMatches: (runId: string) =>
    request<RuleMatch[]>(`/api/rules/runs/${encodeURIComponent(runId)}/matches`),
  providers: () => request<ProviderConfig[]>("/api/providers"),
  addProvider: (body: ProviderInput) => request<ProviderConfig>("/api/providers", post(body)),
  updateProvider: (id: string, body: ProviderInput) =>
    request<ProviderConfig>(`/api/providers/${encodeURIComponent(id)}`, patch(body)),
  deleteProvider: (id: string) =>
    request<void>(`/api/providers/${encodeURIComponent(id)}`, { method: "DELETE" }),
  testProvider: (id: string) =>
    request<ProviderHealth>(`/api/providers/${encodeURIComponent(id)}/test`, { method: "POST" }),
  askProviders: () => request<AskProvider[]>("/api/ask/providers"),
  ask: (body: AskRequest, signal?: AbortSignal) =>
    request<AskResponse>("/api/ask", { ...post(body), signal }),
  columns: () => request<ColumnInfo[]>("/api/schema/columns"),
  authState: () => request<AuthState>("/api/auth/state"),
  setup: (body: { token: string; username: string; password: string }) =>
    request<SignedIn>("/api/setup", post(body)),
  login: (body: { username: string; password: string }) =>
    request<SignedIn>("/api/auth/login", post(body)),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  /** Where to send the browser for single sign-on; a link token finishes an invite or reset. */
  startSso: (linkToken?: string) =>
    request<{ url: string }>(
      "/api/auth/sso/start",
      post(linkToken ? { link_token: linkToken } : {}),
    ),
  sources: () => request<Source[]>("/api/sources"),
  templates: () => request<TemplateInfo[]>("/api/templates"),
  drafts: () => request<DraftInfo[]>("/api/templates/drafts"),
  draft: (id: string) => request<Draft>(`/api/templates/drafts/${encodeURIComponent(id)}`),
  createDraft: (body: {
    template_id: string;
    from_template?: string | null;
    sample: DraftSampleInput;
  }) => request<Draft>("/api/templates/drafts", post(body)),
  updateDraft: (id: string, body: { yaml?: string; sample?: DraftSampleInput }) =>
    request<Draft>(`/api/templates/drafts/${encodeURIComponent(id)}`, put(body)),
  deleteDraft: (id: string) =>
    request<void>(`/api/templates/drafts/${encodeURIComponent(id)}`, { method: "DELETE" }),
  previewDraft: (id: string, yaml?: string) =>
    request<DraftPreview>(
      `/api/templates/drafts/${encodeURIComponent(id)}/preview`,
      post(yaml === undefined ? {} : { yaml }),
    ),
  aiDraft: (id: string, providerId: string) =>
    request<Draft>(
      `/api/templates/drafts/${encodeURIComponent(id)}/ai-draft`,
      post({ provider_id: providerId }),
    ),
  /** `sha256` is the preview the admin reviewed; the server refuses a draft saved since. */
  approveDraft: (id: string, sha256: string) =>
    request<TemplateApproval>(
      `/api/templates/drafts/${encodeURIComponent(id)}/approve`,
      post({ sha256 }),
    ),
  users: () => request<ManagedUser[]>("/api/users"),
  inviteUser: (body: { username: string; role: Role }) =>
    request<{ user: ManagedUser; invite_token: string }>("/api/users", post(body)),
  updateUser: (id: string, body: { role?: Role; disabled?: boolean }) =>
    request<ManagedUser>(`/api/users/${encodeURIComponent(id)}`, patch(body)),
  resetUser: (id: string) =>
    request<{ reset_token: string }>(`/api/users/${encodeURIComponent(id)}/reset`, {
      method: "POST",
    }),
  setPasswordFromLink: (body: { token: string; password: string }) =>
    request<void>("/api/account/password", post(body)),
  searches: () => request<SavedSearch[]>("/api/searches"),
  createSearch: (body: SavedSearchInput) => request<SavedSearch>("/api/searches", post(body)),
  updateSearch: (body: SavedSearchInput) =>
    request<SavedSearch>(`/api/searches/${encodeURIComponent(body.id)}`, put(body)),
  verifySearch: (id: string, verified: boolean) =>
    request<SavedSearch>(`/api/searches/${encodeURIComponent(id)}/verified`, put({ verified })),
  deleteSearch: (id: string) =>
    request<void>(`/api/searches/${encodeURIComponent(id)}`, { method: "DELETE" }),
  runSearch: (id: string, body: { params: Record<string, string>; start?: string }) =>
    request<QueryResult>(`/api/searches/${encodeURIComponent(id)}/run`, post(body)),
  exportSearch: (id: string) => requestText(`/api/searches/${encodeURIComponent(id)}/export`),
  importSearch: (yamlText: string) => postYaml<SavedSearch>("/api/searches/import", yamlText),
  tokens: () => request<ApiToken[]>("/api/tokens"),
  createToken: (body: { label: string; days: number }) =>
    request<ApiToken & { token: string }>("/api/tokens", post(body)),
  revokeToken: (id: string) =>
    request<void>(`/api/tokens/${encodeURIComponent(id)}`, { method: "DELETE" }),
  signOutUser: (id: string) =>
    request<void>(`/api/users/${encodeURIComponent(id)}/signout`, { method: "POST" }),
  groups: () => request<SourceGroup[]>("/api/groups"),
  groupSuggestions: () => request<GroupSuggestion[]>("/api/groups/suggestions"),
  acceptGroupSuggestion: (body: {
    kind: GroupSuggestion["kind"];
    key: string;
    source_ids: string[];
  }) => request<SourceGroup>("/api/groups/suggestions/accept", post(body)),
  createGroup: (body: { name: string; description: string }) =>
    request<SourceGroup>("/api/groups", post(body)),
  deleteGroup: (id: string) =>
    request<void>(`/api/groups/${encodeURIComponent(id)}`, { method: "DELETE" }),
  setGroupSources: (id: string, sourceIds: string[]) =>
    request<SourceGroup>(
      `/api/groups/${encodeURIComponent(id)}/sources`,
      put({ source_ids: sourceIds }),
    ),
  setGroupMembers: (id: string, userIds: string[]) =>
    request<SourceGroup>(
      `/api/groups/${encodeURIComponent(id)}/members`,
      put({ user_ids: userIds }),
    ),
  sourceSettings: () => request<{ allowed_roots: string[] }>("/api/sources/settings"),
  addSource: (body: SourceInput) =>
    request<Source & { otlp_token?: string | null }>("/api/sources", post(body)),
  rotateOtlpToken: (id: string) =>
    request<{ token: string }>(`/api/sources/${encodeURIComponent(id)}/otlp-token`, {
      method: "POST",
    }),
  setKeepContent: (id: string, keep: boolean) =>
    request<Source>(`/api/sources/${encodeURIComponent(id)}`, patch({ otlp_keep_content: keep })),
  agentConfig: (id: string, os: "windows" | "linux") =>
    requestText(`/api/sources/${encodeURIComponent(id)}/agent-config?os=${os}`),
  testLoki: (body: LokiSettings & { secret?: string }) =>
    request<LokiTestResult>("/api/sources/loki/test", post(body)),
  testApiSource: (body: {
    kind: "m365" | "anthropic";
    m365?: M365Settings;
    anthropic?: AnthropicSettings;
    credentials: ApiCredentials;
  }) => request<ApiTestResult>("/api/sources/api/test", post(body)),
  replaceCredentials: (id: string, credentials: ApiCredentials) =>
    request<void>(`/api/sources/${encodeURIComponent(id)}/credentials`, put(credentials)),
  discoverSources: (path: string) =>
    request<DiscoveryReport>("/api/sources/discover", post({ path })),
  /** Admins: change a source's label. Only new events take it (SPEC 6.2). */
  setSourceTimezone: (id: string, timezone: string) =>
    request<Source>(`/api/sources/${encodeURIComponent(id)}`, patch({ timezone })),
  classifySource: (id: string, classification: "local_only" | "cloud_allowed") =>
    request<Source>(`/api/sources/${encodeURIComponent(id)}`, patch({ classification })),
  /** null is the generic parser, "auto" the Automatic one (ADR-0012). New lines only. */
  setSourceParser: (id: string, templateId: string | null) =>
    request<Source>(`/api/sources/${encodeURIComponent(id)}`, patch({ template_id: templateId })),
  sourceWatches: () => request<SourceWatch[]>("/api/sources/watches"),
  /** null turns the alert off. Admins only; audited. */
  setSourceWatch: (id: string, quietAfterS: number | null, targetIds: string[]) =>
    request<SourceWatch | null>(
      `/api/sources/${encodeURIComponent(id)}/watch`,
      put({ quiet_after_s: quietAfterS, target_ids: targetIds }),
    ),
  deleteSource: (id: string) =>
    request<void>(`/api/sources/${encodeURIComponent(id)}`, { method: "DELETE" }),
  meta: () => request<Meta>("/api/meta"),
  health: () => request<Health>("/api/health"),
  /** Server-side CSV of the same query, audited as an export. */
  exportCsv: (body: QueryRequest) => request<string>("/api/query/export", post(body), true),
  refineQuery: (body: { sql: string; field: string; value: string | null; exclude: boolean }) =>
    request<{ sql: string }>("/api/query/refine", post(body)),
  mcpSettings: () => request<McpSettings>("/api/mcp/settings"),
  saveMcpSettings: (body: { enabled: boolean; endpoint_local: boolean }) =>
    request<McpSettings>("/api/mcp/settings", put(body)),
  facets: (body: FacetRequest) =>
    request<{ facets: Facet[]; elapsed_ms: number }>("/api/search/facets", post(body)),
  searchPresets: () => request<SearchPreset[]>("/api/search/presets"),
  healthChecks: () => request<HealthChecks>("/api/health-checks"),
  handoff: (body: { target_id: string; event_ids: string[]; note: string }) =>
    request<{ target_id: string; sent: number; withheld_local_only: number; not_found: number }>(
      "/api/handoff",
      post(body),
    ),
  enrichment: () => request<EnrichmentStatus>("/api/enrichment"),
  setEnrichmentAuto: (auto_update: boolean) =>
    request<EnrichmentStatus>("/api/enrichment/settings", put({ auto_update })),
  setFeed: (id: string, body: { enabled?: boolean; key?: string }) =>
    request<EnrichmentFeed>(`/api/enrichment/feeds/${encodeURIComponent(id)}`, put(body)),
  updateFeed: (id: string) =>
    request<EnrichmentFeed>(`/api/enrichment/feeds/${encodeURIComponent(id)}/update`, post({})),
  uploadFeed: (id: string, file: Blob) =>
    request<EnrichmentFeed>(`/api/enrichment/feeds/${encodeURIComponent(id)}/upload`, {
      method: "POST",
      body: file,
    }),
  integrity: () => request<IntegrityStatus>("/api/integrity"),
  verifyIntegrity: () => request<IntegritySeal>("/api/integrity/verify", post({})),
  integrityReport: (days: number) =>
    request<Record<string, unknown>>(`/api/integrity/report?days=${days}`),
  saveIntegritySettings: (body: { target_ids: string[]; send_seals: boolean }) =>
    request<IntegritySettings>("/api/integrity/settings", put(body)),
  aiAgents: () => request<AiAgent[]>("/api/ai/agents"),
  setAiDataLevel: (id: string, level: DataLevel | null) =>
    request<AiService>(
      `/api/ai/services/${encodeURIComponent(id)}/data-level`,
      put({ data_level: level }),
    ),
  addressHolders: (ip: string, at?: string) =>
    request<AddressHolders>(
      `/api/addresses/${encodeURIComponent(ip)}${at ? `?at=${encodeURIComponent(at)}` : ""}`,
    ),
  addWatchedDevice: (body: WatchedDeviceInput) =>
    request<{ device_id: string }>("/api/health-checks/devices", post(body)),
  changeWatchedDevice: (id: string, body: WatchedDeviceInput) =>
    request<{ device_id: string }>(
      `/api/health-checks/devices/${encodeURIComponent(id)}`,
      put(body),
    ),
  removeWatchedDevice: (id: string) =>
    request<void>(`/api/health-checks/devices/${encodeURIComponent(id)}`, { method: "DELETE" }),
  identities: () => request<Identities>("/api/identities"),
  setIdentityDomains: (domains: string[]) =>
    request<string[]>("/api/identities/domains", put({ domains })),
  setIdentityAlias: (alias: string, person: string | null) =>
    request<IdentityAlias[]>("/api/identities/aliases", put({ alias, person })),
  entityRisk: (start?: string) =>
    request<RiskResponse>(
      `/api/entities/risk${start ? `?start=${encodeURIComponent(start)}` : ""}`,
    ),
  entityGraph: (q: { mode: "entity" | "ai"; kind?: GraphKind; value?: string; start?: string }) => {
    const p = new URLSearchParams({ mode: q.mode });
    if (q.kind) p.set("kind", q.kind);
    if (q.value) p.set("value", q.value);
    if (q.start) p.set("start", q.start);
    return request<EntityGraph>(`/api/entities/graph?${p.toString()}`);
  },
  aiUsage: (start?: string) =>
    request<AiUsage>(`/api/ai/usage${start ? `?start=${encodeURIComponent(start)}` : ""}`),
  aiCatalog: () => request<AiService[]>("/api/ai/catalog"),
  setAiServiceStatus: (id: string, status: AiStatus) =>
    request<AiService>(`/api/ai/services/${encodeURIComponent(id)}/status`, put({ status })),
  addAiService: (body: {
    id: string;
    name: string;
    vendor: string;
    kind: string;
    domains: string[];
  }) => request<AiService>("/api/ai/services", post(body)),
  deleteAiService: (id: string) =>
    request<void>(`/api/ai/services/${encodeURIComponent(id)}`, { method: "DELETE" }),
  aiMcpRules: () => request<AiMcpRule[]>("/api/ai/mcp-rules"),
  setAiMcpRule: (pattern: string, status: "approved" | "not_approved" | null) =>
    request<AiMcpRule[]>("/api/ai/mcp-rules", put({ pattern, status })),
  aiWatch: () => request<AiWatch>("/api/ai/watch"),
  setAiWatch: (
    body: Pick<AiWatch, "enabled" | "include_unreviewed" | "sensitive" | "target_ids">,
  ) => request<AiWatch>("/api/ai/watch", put(body)),
  compileSearch: (text: string, top?: string) =>
    request<CompiledSearch>("/api/search/compile", post({ text, top })),
  query: (body: QueryRequest) =>
    request<QueryResult>("/api/query", { method: "POST", body: JSON.stringify(body) }),
};
