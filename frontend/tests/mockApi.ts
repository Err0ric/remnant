import { vi } from "vitest";

const ID = "01a126d0-7c4f-7012-b6b0-e17359887d5f";

export const FULL_EVENT = {
  columns: [
    "event_id",
    "source_id",
    "time",
    "device_hostname",
    "actor_process_name",
    "message",
    "raw",
    "classification",
    "parse_status",
  ],
  rows: [
    [
      ID,
      "linux_sshd",
      "2026-10-09T23:04:36+00:00",
      "bastion",
      "sshd",
      "Failed password for invalid user oracle",
      "<38>Oct  9 23:04:36 bastion sshd[4032]: Failed password for invalid user oracle",
      "local_only",
      "envelope_only",
    ],
  ],
};

const RESULTS = {
  columns: [
    "time",
    "severity_id",
    "source_id",
    "device_hostname",
    "actor_process_name",
    "message",
    "event_id",
  ],
  rows: [
    [
      "2026-10-09T23:04:36+00:00",
      3,
      "linux_sshd",
      "bastion",
      "sshd",
      "Failed password for invalid user oracle",
      ID,
    ],
    [
      "2026-10-09T22:54:36+00:00",
      1,
      "linux_sshd",
      "bastion",
      "sshd",
      null,
      "01a126d0-7c4f-7011-80b9-fbafec14197f",
    ],
  ],
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function result(r: { columns: string[]; rows: unknown[][] }) {
  return {
    ...r,
    row_count: r.rows.length,
    truncated: false,
    elapsed_ms: 7,
    executed_sql: "SELECT ...",
    sources: ["linux_sshd"],
  };
}

export interface MockAuth {
  mode: "open" | "setup" | "login";
  signedIn?: boolean;
  role?: "admin" | "analyst" | "auditor";
  /** No accounts yet: the user list starts empty (a fresh loopback install). */
  noAccounts?: boolean;
  /** The sign-out request fails on the server. */
  logoutFails?: boolean;
  /** Single sign-on turned on, with this button label. */
  sso?: string;
}

export const SOURCE = {
  source_id: "linux_sshd",
  format: "syslog",
  path: "/logs/bastion",
  glob: "**/*.log",
  timezone: "UTC",
  retention_days: 30,
  classification: "local_only",
  enabled: true,
  status: {
    state: "reading",
    files: 2,
    last_pass_at: "2026-10-10T18:00:00Z",
    last_event_at: "2026-10-10T18:00:00Z",
    events_since_start: 69,
    error: null,
    records_skipped: 0,
    files_waiting: 0,
  },
};

export function mockApi(productName = "TestProduct", auth: MockAuth = { mode: "open" }) {
  const state = { ...auth };
  const sources: Record<string, unknown>[] = [{ ...SOURCE }];
  const watched: Record<string, unknown>[] = [
    {
      device_id: "d0",
      name: "Site B network sensor",
      match: "10.40.2.21",
      silence_s: 900,
      target_ids: [],
      state: "unhealthy",
      reason: "Silent 47 min (allowed 15 min)",
      last_seen: "2026-10-10T11:13:00+00:00",
      hourly: Array(24).fill(3),
    },
  ];
  const users: Record<string, unknown>[] = [
    {
      user_id: "u1",
      username: "jordan",
      role: "admin",
      disabled: false,
      pending: false,
      created_at: "2026-10-10T18:00:00Z",
      last_login_at: "2026-10-10T19:00:00Z",
    },
    {
      user_id: "u2",
      username: "kelly",
      role: "analyst",
      disabled: false,
      pending: false,
      created_at: "2026-10-10T18:10:00Z",
      last_login_at: null,
    },
  ];
  if (auth.noAccounts) users.length = 0;
  const searches: Record<string, unknown>[] = [
    {
      id: "failed_by_ip",
      name: "Failed SSH by source",
      description: "Top sources",
      tags: ["auth"],
      visibility: "shared",
      sources: null,
      sql: "SELECT 1 LIMIT {{top}}",
      params: [{ name: "top", type: "int", default: 25 }],
      mode: "ask",
      origin: { ask_prompt: "which IPs failed SSH the most?" },
      owner_id: "someone-else",
      verified: false,
      created_at: "2026-10-10T10:00:00Z",
      updated_at: "2026-10-10T10:00:00Z",
    },
  ];
  let askBusySeen = false;
  const tokens: Record<string, unknown>[] = [
    {
      token_id: "t1",
      label: "CLI on laptop-01",
      created_at: "2026-10-01T10:00:00Z",
      expires_at: "2026-10-31T10:00:00Z",
      last_used_at: "2026-10-10T09:00:00Z",
    },
  ];
  const groups: Record<string, unknown>[] = [
    {
      group_id: "g1",
      name: "Security",
      description: "",
      source_ids: ["linux_sshd"],
      user_ids: ["u2"],
    },
  ];
  const rule = (id: string, title: string, author: string, enabled: boolean) => ({
    rule_id: id,
    title,
    author,
    level: "high",
    status: "test",
    product: "windows",
    service: "security",
    category: null,
    tags: ["attack.t1110"],
    path: `windows/${id}.yml`,
    enabled,
    sha256: "ab".repeat(32),
    import_id: "imp1",
    updated_at: "2026-10-11T00:00:00+00:00",
    source_ids: enabled ? ["win_dc"] : [],
  });
  const rules = [
    rule("r1", "Failed logon burst", "Jane Doe", true),
    rule("r2", "Disabled example", "", false),
  ];
  const ruleRuns: Record<string, unknown>[] = [];
  const runSummary = (id: string, count: number | null, extra: Record<string, unknown> = {}) => ({
    run_id: id,
    started_at: "2026-10-11T07:00:00+00:00",
    range_start: "2026-10-10T07:00:00+00:00",
    range_end: "2026-10-11T07:00:00+00:00",
    status: "ok",
    restricted: false,
    row_count: count,
    elapsed_ms: 5,
    sources_in_scope: ["lin_auth"],
    flagged: false,
    flag_reason: null,
    error: null,
    rule_run_id: null,
    ...extra,
  });
  const watches: Record<string, unknown>[] = [];
  const alertTargets: Record<string, unknown>[] = [
    {
      target_id: "t1",
      name: "SOC Slack",
      kind: "slack",
      display: "hooks.slack.com",
      recipients: [],
      failing: false,
      consecutive_failures: 0,
      last_error: null,
      last_sent_at: "2026-10-11T07:00:00+00:00",
    },
  ];
  const schedules: Record<string, unknown>[] = [
    {
      schedule_id: "s1",
      kind: "search",
      target_id: "failed_by_ip",
      name: "Failed SSH daily",
      owner_id: "u1",
      mine: true,
      shared: false,
      cron: "0 7 * * *",
      lookback_minutes: 1440,
      params: { top: 5 },
      threshold_kind: "above",
      threshold_value: 10,
      paused: false,
      paused_reason: null,
      next_run_at: "2026-10-12T07:00:00+00:00",
      last_run_at: "2026-10-11T07:00:00+00:00",
      created_at: "2026-10-10T00:00:00+00:00",
      target_ids: ["t1"],
      recent: [
        runSummary("sr2", 12, {
          flagged: true,
          flag_reason: "12 is above 10",
          parser_change:
            "Parser changed for lin_auth at 2026-10-11 03:00 UTC (generic_syslog to linux_sshd). Searches on message may no longer match: use raw or parsed fields.",
        }),
        runSummary("sr1", 3),
      ],
    },
    {
      schedule_id: "s2",
      kind: "rule",
      target_id: "r1",
      name: "Windows failures",
      owner_id: "someone-else",
      mine: false,
      shared: true,
      cron: "0 * * * *",
      lookback_minutes: null,
      params: {},
      threshold_kind: null,
      threshold_value: null,
      paused: false,
      paused_reason: null,
      next_run_at: "2026-10-11T08:00:00+00:00",
      last_run_at: "2026-10-11T07:00:00+00:00",
      created_at: "2026-10-10T00:00:00+00:00",
      target_ids: [],
      recent: [runSummary("sr3", null, { restricted: true, sources_in_scope: [] })],
    },
  ];
  const providers: Record<string, unknown>[] = [
    {
      provider_id: "p1",
      name: "Local Ollama",
      kind: "openai_compat",
      base_url: "http://ollama:11434/v1",
      model: "",
      enabled: false,
      has_api_key: false,
      locality: "local",
      host_found: true,
      redact: false,
    },
  ];
  const drafts: Record<string, Record<string, unknown>> = {};
  const DRAFT_YAML = "schema_version: 1\nid: ID\nname: Widget\nversion: 0.1.0\n";
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const user = { user_id: "u1", username: "jordan", role: state.role ?? "admin" };
    const method = (init?.method ?? "GET").toUpperCase();
    const draftMatch = /\/api\/templates\/drafts\/([^/]+)(\/preview|\/approve|\/ai-draft)?$/.exec(
      url,
    );
    if (url.endsWith("/api/templates/drafts") && method === "GET")
      return json(Object.values(drafts));
    if (url.endsWith("/api/templates/drafts") && method === "POST") {
      const body = JSON.parse(String(init?.body)) as {
        template_id: string;
        sample: { kind: string; text?: string };
      };
      if (body.template_id === "linux_sshd")
        return json({ detail: "linux_sshd is a starter template" }, 409);
      const lines = (body.sample.text ?? "").split("\n").filter((l) => l.trim()).length;
      drafts[body.template_id] = {
        template_id: body.template_id,
        created_by: "u1",
        created_at: "2026-10-10T18:00:00Z",
        updated_at: "2026-10-10T18:00:00Z",
        sample: { kind: body.sample.kind, path: null, glob: null, lines },
        llm_call_id: null,
        replaces_version: null,
        yaml: DRAFT_YAML.replace("ID", body.template_id),
      };
      return json(drafts[body.template_id], 201);
    }
    if (draftMatch) {
      const id = decodeURIComponent(draftMatch[1] ?? "");
      const d = drafts[id];
      if (!d) return json({ detail: `No draft named ${id}` }, 404);
      if (draftMatch[2] === "/preview") {
        const { yaml } = JSON.parse(String(init?.body ?? "{}")) as { yaml?: string };
        const text = yaml ?? String(d.yaml);
        const broken = text.includes("BROKEN") || id.includes("broken");
        return json({
          valid: !broken,
          errors: broken ? ["mapping: field required"] : [],
          tests: broken ? [] : [{ name: "sample line 1", passed: true, problems: [] }],
          lines: 2,
          ok: 2,
          partial: 0,
          failed: 0,
          rows: broken
            ? []
            : [
                {
                  line: 1,
                  raw: "<b>widget</b> started",
                  parse_status: "ok",
                  parse_errors: null,
                  class_uid: 0,
                  fields: { message: "widget started" },
                },
              ],
          approvable: !broken,
          sha256: "cd".repeat(32),
        });
      }
      if (draftMatch[2] === "/ai-draft") {
        d.yaml = String(d.yaml) + "payload:\n  format: kv\n";
        d.llm_call_id = "call-1";
        return json(d);
      }
      if (draftMatch[2] === "/approve") {
        delete drafts[id];
        return json({
          approval_id: "a1",
          template_id: id,
          version: "0.1.0",
          sha256: "ab".repeat(32),
          approved_by: "u1",
          approved_at: "2026-10-10T18:05:00Z",
        });
      }
      if (method === "PUT") {
        const body = JSON.parse(String(init?.body)) as { yaml?: string };
        if (body.yaml !== undefined) d.yaml = body.yaml;
        return json(d);
      }
      if (method === "DELETE") {
        delete drafts[id];
        return new Response(null, { status: 204 });
      }
      return json(d);
    }
    if (url.endsWith("/api/groups/suggestions"))
      return json([
        {
          kind: "category",
          key: "identity",
          name: "Identity",
          group_id: null,
          source_ids: ["linux_sshd", "linux_sudo"],
          missing: ["linux_sshd", "linux_sudo"],
        },
      ]);
    if (url.endsWith("/api/groups/suggestions/accept"))
      return json({
        group_id: "g9",
        name: "Identity",
        description: "",
        source_ids: ["linux_sshd"],
        user_ids: [],
      });
    if (url.endsWith("/api/users") && method === "GET") {
      if (state.mode === "login" && !state.signedIn)
        return json({ detail: "Sign in to continue", code: "auth_required" }, 401);
      return json(users);
    }
    if (url.endsWith("/api/users") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as { username: string; role: string };
      const created = {
        user_id: `u${users.length + 1}`,
        username: body.username,
        role: body.role,
        disabled: false,
        pending: true,
        created_at: "2026-10-10T20:00:00Z",
        last_login_at: null,
      };
      users.push(created);
      if (state.mode === "open") state.mode = "login"; // the first account ends open mode
      return json({ user: created, invite_token: "invite-token-123" }, 201);
    }
    if (/\/api\/users\/[^/]+\/reset$/.test(url)) return json({ reset_token: "reset-token-456" });
    if (/\/api\/users\/[^/]+$/.test(url) && method === "PATCH") {
      const id = url.split("/api/users/")[1];
      const body = JSON.parse(String(init?.body ?? "{}")) as { role?: string; disabled?: boolean };
      if (id === "u1" && (body.disabled || (body.role && body.role !== "admin")))
        return json(
          {
            detail: "This is the last active administrator. Add another admin first",
            code: "last_admin",
          },
          409,
        );
      const u = users.find((x) => x.user_id === id);
      Object.assign(u ?? {}, body);
      return json(u);
    }
    if (url.endsWith("/api/searches") && method === "GET") return json(searches);
    if (url.endsWith("/api/searches") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const created = {
        ...body,
        owner_id: "u1",
        verified: false,
        created_at: "x",
        updated_at: "x",
      };
      searches.push(created);
      return json(created, 201);
    }
    if (url.endsWith("/api/searches/import")) {
      const created = { ...searches[0], id: "imported_one", owner_id: "u1", visibility: "private" };
      searches.push(created);
      return json(created, 201);
    }
    if (/\/api\/searches\/[^/]+\/verified$/.test(url)) {
      const id = url.split("/api/searches/")[1]?.split("/")[0];
      const found = searches.find((x) => x.id === id);
      Object.assign(found ?? {}, JSON.parse(String(init?.body ?? "{}")));
      return json(found);
    }
    if (/\/api\/searches\/[^/]+$/.test(url) && method === "PUT") {
      const id = url.split("/api/searches/")[1];
      const found = searches.find((x) => x.id === id);
      Object.assign(found ?? {}, JSON.parse(String(init?.body ?? "{}")), { updated_at: "y" });
      return json(found);
    }
    if (/\/api\/searches\/[^/]+\/run$/.test(url))
      return json(result({ columns: ["src", "n"], rows: [["203.0.113.9", 278]] }));
    if (/\/api\/searches\/[^/]+\/export$/.test(url))
      return new Response("schema_version: 1\nid: failed_by_ip\n", { status: 200 });
    if (/\/api\/searches\/[^/]+$/.test(url) && method === "DELETE") {
      const id = url.split("/api/searches/")[1];
      searches.splice(
        searches.findIndex((x) => x.id === id),
        1,
      );
      return new Response(null, { status: 204 });
    }
    if (url.endsWith("/api/tokens") && method === "GET") return json(tokens);
    if (url.endsWith("/api/tokens") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as { label: string };
      const t = {
        token_id: `t${tokens.length + 1}`,
        label: body.label,
        created_at: "2026-10-10T20:00:00Z",
        expires_at: "2027-01-08T20:00:00Z",
        last_used_at: null,
      };
      tokens.push(t);
      return json({ ...t, token: "secret-token-value" }, 201);
    }
    if (url.includes("/api/tokens/") && method === "DELETE") {
      const id = url.split("/api/tokens/")[1];
      tokens.splice(
        tokens.findIndex((t) => t.token_id === id),
        1,
      );
      return new Response(null, { status: 204 });
    }
    if (/\/api\/users\/[^/]+\/signout$/.test(url)) return new Response(null, { status: 204 });
    if (url.endsWith("/api/groups") && method === "GET") return json(groups);
    if (url.endsWith("/api/groups") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as { name: string; description: string };
      const g = { group_id: `g${groups.length + 1}`, ...body, source_ids: [], user_ids: [] };
      groups.push(g);
      return json(g, 201);
    }
    const groupMatch = /\/api\/groups\/([^/]+)(?:\/(sources|members))?$/.exec(url);
    if (groupMatch) {
      const g = groups.find((x) => x.group_id === groupMatch[1]);
      if (method === "DELETE") {
        groups.splice(groups.indexOf(g ?? {}), 1);
        return new Response(null, { status: 204 });
      }
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      Object.assign(g ?? {}, body);
      return json(g);
    }
    if (url.endsWith("/api/account/password")) {
      const body = JSON.parse(String(init?.body ?? "{}")) as { token: string };
      if (body.token !== "invite-token-123")
        return json(
          {
            detail:
              "This link is invalid, expired, or already used. Ask an administrator for a new one",
            code: "link_invalid",
          },
          403,
        );
      return new Response(null, { status: 204 });
    }
    if (url.endsWith("/api/templates"))
      return json([
        {
          id: "linux_sshd",
          name: "Linux sshd authentication",
          version: "1.0.0",
          description: "OpenSSH server authentication events through syslog.",
          category: "identity",
          envelope: "syslog",
          payload_format: "regex",
          class_uid: 3002,
          classification_default: "local_only",
        },
      ]);
    if (url.endsWith("/api/alert-targets") && method === "GET") return json(alertTargets);
    if (url.endsWith("/api/alert-targets") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const created = {
        target_id: `t${alertTargets.length + 1}`,
        name: body.name,
        kind: body.kind,
        display: "127.0.0.1",
        recipients: [],
        failing: false,
        consecutive_failures: 0,
        last_error: null,
        last_sent_at: null,
      };
      alertTargets.push(created);
      return json({ ...created, signing_key: body.kind === "webhook" ? "KEY-ONCE" : null }, 201);
    }
    if (/\/api\/alert-targets\/[^/]+\/test$/.test(url))
      return json({ ok: false, detail: "The destination answered HTTP 500" });
    if (/\/api\/schedules\/[^/]+\/deliveries$/.test(url))
      return json([
        {
          delivery_id: "d1",
          target_name: "SOC Slack",
          kind: "flag",
          status: "failed",
          attempts: 4,
          next_attempt_at: null,
          last_error: "The destination answered HTTP 503",
          created_at: "2026-10-11T07:00:00+00:00",
          sent_at: null,
        },
      ]);
    if (url.endsWith("/api/identities/domains") && method === "PUT") {
      const body = JSON.parse(String(init?.body ?? "{}")) as { domains: string[] };
      return json(body.domains.map((d) => d.toLowerCase()));
    }
    if (url.endsWith("/api/identities/aliases") && method === "PUT") return json([]);
    if (url.endsWith("/api/identities"))
      return json({
        domains: [],
        aliases: [
          {
            alias: "jsmith",
            person: "john.smith@example.com",
            created_by: "u1",
            created_at: "2026-10-15T06:00:00Z",
          },
        ],
        domain_suggestions: [
          { domain: "example.com", addresses: 3, shared: 2, examples: ["alice", "bob"] },
        ],
        alias_suggestions: [{ alias: "carol", person: "carol@example.com", hosts: ["ws-0311"] }],
      });
    if (url.includes("/api/entities/risk")) {
      const r = (kind: string, value: string, high: number, rules: string[]) => ({
        kind,
        value,
        score: 5 * high,
        critical: 0,
        high,
        medium: 0,
        low: 0,
        flagged_runs: 0,
        events: high,
        rules,
        search_sql: `SELECT * FROM events WHERE actor_user_name = '${value}'`,
      });
      return json({
        users: [
          r("user", "root", 4, ["SSH failed password"]),
          r("user", "deploy", 1, ["SSH failed password"]),
        ],
        ips: [r("ip", "203.0.113.9", 4, ["SSH failed password"])],
        hosts: [],
        matches_considered: 5,
        sources: ["linux_sshd"],
      });
    }
    if (url.endsWith("/api/ai/agents") && method === "GET")
      return json([
        {
          kind: "Claude Code",
          agent: "cc|ws-0042|alice@example.com",
          label: "Claude Code on ws-0042",
          owners: ["alice@example.com"],
          machine: "ws-0042",
          first_seen: "2026-09-20T10:00:00+00:00",
          last_seen: "2026-10-10T11:30:00+00:00",
          events_24h: 42,
          state: "changed",
          new_items: [{ kind: "MCP server", name: "paste-share" }],
          usual_peak: null,
          recent_peak: null,
        },
      ]);
    if (url.endsWith("/api/health-checks") && method === "GET")
      return json({
        devices: watched,
        agents: [
          {
            kind: "OpenTelemetry",
            source_id: "claude",
            machine: "ws-0042",
            last_seen: "2026-10-08T09:00:00+00:00",
            events_24h: 0,
            state: "attention",
            reason: "Last reported 2 d ago",
          },
        ],
      });
    if (url.endsWith("/api/health-checks/devices") && method === "POST") {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      watched.push({
        device_id: `d${watched.length + 1}`,
        name: body.name,
        match: String(body.match).toLowerCase(),
        silence_s: body.silence_s,
        target_ids: body.target_ids,
        state: "unknown",
        reason: "Not seen in the last 24 hours",
        last_seen: null,
        hourly: Array(24).fill(0),
      });
      return json({ device_id: `d${watched.length}` }, 201);
    }
    if (url.includes("/api/entities/graph")) {
      const q = new URL(url, "https://x").searchParams;
      const card = (id: string, lane: number, label: string, extra: object = {}) => ({
        id,
        lane,
        label,
        sublabel: "",
        events: 4,
        matches: 0,
        max_severity: 0,
        badges: [],
        search_sql: `SELECT * FROM events WHERE message = '${label}'`,
        group: "",
        ...extra,
      });
      if (q.get("mode") === "ai")
        return json({
          mode: "ai",
          lanes: ["People", "AI clients", "Tools and MCP servers", "Destinations"],
          cards: [
            card("0:alice@example.com", 0, "alice@example.com", { group: "People" }),
            card("1:Claude Code", 1, "Claude Code"),
            card("2:paste-share", 2, "paste-share", {
              badges: ["Not approved"],
              group: "MCP servers",
            }),
            card("2:Read", 2, "Read", { group: "Built-in tools" }),
            card("3:svc:chatgpt", 3, "ChatGPT", {
              sublabel: "OpenAI",
              search_sql: null,
              group: "AI services",
            }),
          ],
          edges: [
            { source: "0:alice@example.com", target: "1:Claude Code", events: 4 },
            { source: "1:Claude Code", target: "2:paste-share", events: 2 },
            { source: "1:Claude Code", target: "2:Read", events: 2 },
          ],
          more: [0, 0, 0, 0],
          sources: ["claude"],
        });
      const value = q.get("value") ?? "";
      return json({
        mode: "entity",
        lanes: ["Entity", "Sources", "Activities", "Targets"],
        cards: [
          card("0:root", 0, value, { sublabel: "User", matches: 4, badges: ["4 rule matches"] }),
          card("1:linux_sshd", 1, "linux_sshd"),
          card("2:3002|Failed password", 2, "Failed password", {
            sublabel: "Authentication",
            group: "Authentication",
          }),
          card("2:3002|Accepted publickey", 2, "Accepted publickey", {
            sublabel: "Authentication",
            group: "Authentication",
          }),
          card("3:bastion", 3, "bastion", { group: "Hosts" }),
        ],
        edges: [
          { source: "0:root", target: "1:linux_sshd", events: 4 },
          { source: "1:linux_sshd", target: "2:3002|Failed password", events: 3 },
          { source: "1:linux_sshd", target: "2:3002|Accepted publickey", events: 1 },
          { source: "2:3002|Failed password", target: "3:bastion", events: 3 },
        ],
        more: [0, 0, 0, 2],
        sources: ["linux_sshd"],
      });
    }
    if (url.includes("/api/ai/usage")) {
      const svc = (id: string, name: string, status: string) => ({
        id,
        name,
        vendor: "Vendor",
        kind: "chat",
        domains: [`${id}.example`],
        status,
        custom: false,
        note: "",
      });
      return json({
        services: [
          {
            service: svc("chatgpt", "ChatGPT", "not_approved"),
            events: 120,
            people: 3,
            machines: 4,
            first_seen: "2026-10-09T10:00:00+00:00",
            last_seen: "2026-10-10T11:00:00+00:00",
            top_people: ["alice", "bob"],
            top_machines: [],
          },
          {
            service: svc("claude", "Claude", "approved"),
            events: 40,
            people: 2,
            machines: 2,
            first_seen: null,
            last_seen: "2026-10-10T11:30:00+00:00",
            top_people: [],
            top_machines: ["10.20.1.5"],
          },
        ],
        non_usage: [
          {
            service: {
              ...svc("openai_ad_tags", "OpenAI ad and measurement tags", "unreviewed"),
              kind: "non_usage",
              domains: ["bzr.openai.com", "bzrcdn.openai.com"],
            },
            events: 900,
            people: 0,
            machines: 30,
            first_seen: null,
            last_seen: "2026-10-10T11:45:00+00:00",
            top_people: [],
            top_machines: [],
          },
        ],
        mcp: [
          {
            name: "paste-share",
            status: "unreviewed",
            calls: 7,
            people: 1,
            machines: 1,
            installs: 1,
            clients: ["cursor"],
            first_seen: null,
            last_seen: "2026-10-10T11:00:00+00:00",
            sources: ["inventory", "telemetry"],
          },
        ],
        people: [
          {
            person: "alice@example.com",
            cost_usd: 12.5,
            tokens: 400000,
            sessions: 9,
            tool_calls: 120,
            errors: 2,
            sensitive: 1,
            models: ["claude-opus-5-5"],
          },
        ],
        sources_in_scope: ["dns", "claude"],
        compared_from: "2026-09-26T12:00:00+00:00",
        new_services: ["chatgpt"],
        new_mcp: [],
        gone: [
          {
            kind: "service",
            id: "copilot",
            name: "Copilot",
            status: "approved",
            last_seen: "2026-10-01T09:00:00+00:00",
          },
        ],
      });
    }
    if (/\/api\/ai\/services\/[^/]+\/status$/.test(url) && method === "PUT") {
      const id = decodeURIComponent(url.split("/api/ai/services/")[1]?.split("/")[0] ?? "");
      const body = JSON.parse(String(init?.body ?? "{}")) as { status: string };
      return json({
        id,
        name: id,
        vendor: "",
        kind: "chat",
        domains: [],
        status: body.status,
        custom: false,
        note: "",
      });
    }
    if (url.endsWith("/api/ai/catalog")) return json([]);
    if (url.endsWith("/api/ai/mcp-rules")) return json([]);
    if (url.endsWith("/api/ai/watch") && method === "GET")
      return json({
        enabled: false,
        include_unreviewed: false,
        sensitive: true,
        target_ids: [],
        updated_at: null,
        updated_by: null,
      });
    if (url.endsWith("/api/ai/watch") && method === "PUT")
      return json({ ...JSON.parse(String(init?.body ?? "{}")), updated_at: "x", updated_by: "u1" });
    if (url.endsWith("/api/search/presets"))
      return json([
        {
          id: "failed_signins",
          name: "Failed sign-ins",
          description: "Windows 4625 and sshd failures",
          text: 'EventID:4625 OR "failed password"',
        },
        {
          id: "high_severity",
          name: "High and critical severity",
          description: "",
          text: "severity:>=high",
        },
      ]);
    if (url.endsWith("/api/mcp/settings")) {
      if (method === "PUT") {
        const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, boolean>;
        return json({ ...body, updated_at: "2026-10-16T22:00:00Z", path: "/api/mcp" });
      }
      return json({ enabled: false, endpoint_local: false, updated_at: null, path: "/api/mcp" });
    }
    if (url.endsWith("/api/query/refine")) {
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        sql: string;
        field: string;
        value: string | null;
      };
      return json({ sql: `${body.sql}\nWHERE ${body.field} = '${body.value ?? ""}'` });
    }
    if (url.endsWith("/api/search/facets")) {
      const body = JSON.parse(String(init?.body ?? "{}")) as { text?: string; columns?: string[] };
      const all = [
        { field: "source_id", values: [{ value: "linux_sshd", count: 1234 }] },
        {
          field: "src_endpoint_ip",
          values: [
            { value: "203.0.113.9", count: 40 },
            { value: null, count: 3 },
          ],
        },
        { field: "severity_id", values: [{ value: "4", count: 12 }] },
      ];
      const facets =
        body.text !== undefined ? all : all.filter((f) => (body.columns ?? []).includes(f.field));
      return json({ facets, elapsed_ms: 4 });
    }
    if (url.endsWith("/api/search/compile")) {
      const body = JSON.parse(String(init?.body ?? "{}")) as { text: string; top?: string };
      if (body.text.includes("("))
        return json(
          { detail: "The parenthesis at character 1 is never closed", code: "search_invalid" },
          400,
        );
      const cols =
        "time, severity_id, source_id, device_hostname, actor_process_name, message, event_id";
      const where = body.text.trim()
        ? "\nWHERE coalesce(raw ILIKE $p0 ESCAPE '\\' OR message ILIKE $p0 ESCAPE '\\', false)"
        : "";
      const params: Record<string, string> = body.text.trim()
        ? { p0: `%${body.text.trim()}%` }
        : {};
      if (body.top)
        return json({
          sql: `SELECT "${body.top}" AS "${body.top}", count(*) AS events\nFROM events${where}\nGROUP BY 1\nORDER BY 2 DESC, 1\nLIMIT 20`,
          params,
          notes: [],
        });
      return json({
        sql: `SELECT ${cols}\nFROM events${where}\nORDER BY coalesce(time, time_observed) DESC`,
        params,
        notes: body.text.includes("Foo:")
          ? ["Foo is not a column, so it is looked up in unmapped fields"]
          : [],
        columns: body.text.includes("src_ip:") ? ["src_endpoint_ip"] : [],
      });
    }
    if (url.endsWith("/api/handoff") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as { event_ids: string[] };
      return json({
        target_id: "t1",
        sent: body.event_ids.length,
        withheld_local_only: 0,
        not_found: 0,
      });
    }
    if (url.includes("/api/enrichment")) {
      const feed = (id: string, label: string, installed: boolean) => ({
        feed_id: id,
        kind: id.startsWith("intel") ? "intel" : "geoip",
        enabled: true,
        needs_key: id === "intel_threatfox",
        has_key: false,
        downloadable: id !== "intel_custom",
        label,
        provider: "DB-IP Lite",
        terms_url: "https://db-ip.com/db/lite.php",
        level: installed ? "healthy" : "missing",
        version: installed ? "2026-10" : null,
        entries: installed ? 1000 : 0,
        size: installed ? 8_400_000 : 0,
        source: installed ? "download" : null,
        installed_at: installed ? "2026-10-10T12:00:00+00:00" : null,
        checked_at: installed ? "2026-10-10T12:00:00+00:00" : null,
        error: null,
        check_every_s: 86400,
      });
      if (url.endsWith("/update")) return json(feed("geoip_country", "GeoIP country", true));
      if (method === "PUT" && /\/feeds\/[a-z_]+$/.test(url))
        return json({
          ...feed("intel_threatfox", "Indicators of compromise", false),
          has_key: true,
        });
      if (url.endsWith("/upload")) return json(feed("geoip_asn", "GeoIP ASN", true));
      const body =
        method === "PUT"
          ? (JSON.parse(String(init?.body ?? "{}")) as { auto_update: boolean })
          : null;
      return json({
        auto_update: body?.auto_update ?? false,
        feeds: [
          feed("geoip_country", "GeoIP country", true),
          feed("geoip_asn", "GeoIP ASN", false),
          feed("intel_feodo", "Botnet C2 addresses", true),
          feed("intel_threatfox", "Indicators of compromise", false),
          feed("intel_custom", "Your list", false),
        ],
        attribution: "IP Geolocation by DB-IP",
        attribution_url: "https://db-ip.com",
      });
    }
    if (url.includes("/api/integrity")) {
      const seal = (id: number, status: string, at: string) => ({
        seal_id: id,
        at,
        status,
        lake_head: "a".repeat(64),
        lake_seq: 120,
        audit_head: "b".repeat(64),
        audit_rows: 900,
        llm_head: "e".repeat(64),
        llm_rows: 12,
        files: 42,
        failures: status === "failed" ? 1 : 0,
        warnings: 0,
        findings:
          status === "failed"
            ? [
                {
                  severity: "failure",
                  kind: "changed",
                  path: "source=lin_auth/day=2026-10-09/part-0001.parquet",
                  detail: "SHA-256 0011, recorded 2233",
                },
              ]
            : [],
        signature: "c".repeat(64),
        signature_ok: true,
      });
      if (url.endsWith("/api/integrity/verify") && method === "POST")
        return json(seal(3, "verified", "2026-10-10T12:00:00+00:00"));
      if (url.includes("/api/integrity/report"))
        return json({ seals: [], signature: "d".repeat(64) });
      if (url.endsWith("/api/integrity/settings") && method === "PUT")
        return json({ ...JSON.parse(String(init?.body ?? "{}")), updated_at: null });
      const latest = seal(2, "failed", "2026-10-10T11:00:00+00:00");
      return json({
        latest,
        history: [latest, seal(1, "verified", "2026-10-09T11:00:00+00:00")],
        lake_head: "a".repeat(64),
        lake_entries: 120,
        interval_s: 86400,
        settings: { target_ids: [], send_seals: false, updated_at: null },
      });
    }
    if (url.includes("/api/audit/")) {
      if ((state.role ?? "admin") === "analyst")
        return json({ detail: "Not allowed", code: "forbidden" }, 403);
      if (url.includes("/export"))
        return new Response("audit_id,time,user,action\r\n1,t,jordan,user.login\r\n", {
          status: 200,
        });
      const q = new URL(url, "http://x").searchParams;
      if (url.includes("/api/audit/llm-calls"))
        return json([
          {
            call_id: "c1",
            ts: "2026-10-10T11:00:00+00:00",
            user_id: "u2",
            username: "ana",
            provider_id: "p1",
            model: "qwen3.5:9b",
            locality: "local",
            purpose: "ask",
            prompt_ref: "ask.v2@abc123",
            sources_in_scope: ["linux_sshd"],
            classification_result: "allowed",
            redaction_applied: false,
            prompt_sha256: "aa",
            response_sha256: "bb",
            prompt_tokens: 900,
            completion_tokens: 120,
            latency_ms: 2300,
            citation_check: null,
            error: null,
            finished_at: "2026-10-10T11:00:02+00:00",
            provider_name: "Ollama on the LAN",
            chain_hash: "d".repeat(64),
          },
        ]);
      const rows = [
        {
          audit_id: 3,
          ts: "2026-10-10T11:05:00+00:00",
          user_id: "u2",
          username: "ana",
          action: "query.run",
          outcome: "success",
          ip: "192.0.2.10",
          detail: { sql: "SELECT 1" },
        },
        {
          audit_id: 2,
          ts: "2026-10-10T11:00:00+00:00",
          user_id: "u1",
          username: "jordan",
          action: "user.login",
          outcome: "success",
          ip: "192.0.2.5",
          detail: {},
        },
        {
          audit_id: 1,
          ts: "2026-10-10T10:00:00+00:00",
          user_id: null,
          username: null,
          action: "auth.login",
          outcome: "failure",
          ip: "198.51.100.7",
          detail: { username: "root" },
        },
      ];
      const uid = q.get("user_id");
      return json(uid ? rows.filter((r) => r.user_id === uid) : rows);
    }
    if (url.endsWith("/api/overview")) {
      const hours = Array.from({ length: 24 }, (_, i) =>
        new Date(Date.UTC(2026, 9, 9, 13 + i)).toISOString().replace(".000Z", "+00:00"),
      );
      const admin = (state.role ?? "admin") === "admin";
      return json({
        generated_at: "2026-10-10T12:30:00+00:00",
        hours,
        volume: [
          {
            source_id: "linux_sshd",
            counts: hours.map((_, i) => (i % 3) + 1),
            typical: hours.map(() => 2),
            marks: hours.map(() => ""),
          },
          {
            source_id: "win_dc",
            counts: hours.map((_, i) => (i === 23 ? 40 : 0)),
            typical: hours.map(() => 2),
            marks: hours.map((_, i) => (i === 23 ? "busy" : "")),
          },
        ],
        sources: [
          {
            source_id: "linux_sshd",
            state: "reading",
            last_event_at: "2026-10-10T12:26:00+00:00",
            files_waiting: 0,
            records_skipped: 0,
            error: null,
          },
          {
            source_id: "win_dc",
            state: "error",
            last_event_at: null,
            files_waiting: 0,
            records_skipped: 0,
            error: "This source cannot be read right now. An administrator can see why.",
            quiet_since: "2026-10-10T11:00:00+00:00",
          },
        ],
        detections: [
          {
            kind: "rule",
            name: "Failed logon",
            level: "medium",
            count: 6,
            reason: null,
            started_at: "2026-10-10T12:00:00+00:00",
            run_id: "rr1",
            schedule_id: null,
          },
        ],
        paused: [
          {
            schedule_id: "s9",
            name: "Nightly sudo",
            kind: "search",
            reason: "The saved search changed; review it and resume",
          },
        ],
        alerts: admin
          ? {
              targets: [
                {
                  target_id: "t1",
                  name: "SOC Slack",
                  kind: "slack",
                  consecutive_failures: 12,
                  failing: true,
                  last_error: "HTTP 404 from the webhook",
                },
              ],
              failed_deliveries: 2,
            }
          : null,
      });
    }
    if (url.endsWith("/api/schedules") && method === "GET") return json(schedules);
    if (url.endsWith("/api/schedules") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const created = {
        ...schedules[0],
        ...body,
        schedule_id: `s${schedules.length + 1}`,
        name: String(body.name ?? "New"),
        recent: [],
      };
      schedules.push(created);
      return json(created, 201);
    }
    if (/\/api\/schedules\/[^/]+\/runs\/[^/]+$/.test(url))
      return json({
        ...runSummary("sr2", 12),
        columns: ["src", "failures"],
        sample: [
          ["203.0.113.9", 9],
          ["198.51.100.7", 3],
        ],
        truncated: false,
      });
    if (/\/api\/schedules\/[^/]+\/run$/.test(url))
      return json({ ...runSummary("sr9", 1), columns: [], sample: [], truncated: false });
    if (/\/api\/schedules\/[^/]+$/.test(url) && method === "PATCH") {
      const id = url.split("/api/schedules/")[1];
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const found = schedules.find((x) => x.schedule_id === id);
      if (found) Object.assign(found, body);
      return json(found);
    }
    if (/\/api\/schedules\/[^/]+$/.test(url) && method === "DELETE") {
      const id = url.split("/api/schedules/")[1];
      const i = schedules.findIndex((x) => x.schedule_id === id);
      if (i >= 0) schedules.splice(i, 1);
      return new Response(null, { status: 204 });
    }
    if (url.endsWith("/api/rules") && method === "GET") return json(rules);
    if (url.endsWith("/api/rules/runs")) return json(ruleRuns);
    if (url.endsWith("/api/rules/import"))
      return json({
        import_id: "imp2",
        path: "/rules/sigma/rules",
        files: 3,
        accepted: 2,
        new_rules: 0,
        updated: 0,
        unchanged: 2,
        refused: 1,
        truncated: false,
        refusals: [{ path: "windows/x.yml", reason: "Windows service 'iis' is not supported yet" }],
      });
    if (url.endsWith("/api/rules/enabled")) {
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        rule_ids: string[];
        enabled: boolean;
      };
      for (const r of rules) if (body.rule_ids.includes(r.rule_id)) r.enabled = body.enabled;
      return json({ changed: body.rule_ids.length });
    }
    if (/\/api\/rules\/runs\/[^/]+\/matches$/.test(url))
      return json([{ event_id: ID, event_time: "2026-10-10T10:00:00", source_id: "win_dc" }]);
    if (/\/api\/rules\/[^/]+\/run$/.test(url)) {
      const id = url.split("/api/rules/")[1]?.split("/")[0] ?? "";
      const r = rules.find((x) => x.rule_id === id);
      const run = {
        run_id: `run${ruleRuns.length + 1}`,
        rule_id: id,
        sha256: "ab".repeat(32),
        title: r?.title ?? "",
        author: r?.author ?? "",
        level: "high",
        started_by: "u1",
        started_at: "2026-10-11T00:00:00+00:00",
        range_start: "2026-10-10T00:00:00+00:00",
        range_end: "2026-10-11T00:00:00+00:00",
        status: "ok",
        match_count: 1,
        matches_stored: 1,
        elapsed_ms: 12,
        sources_in_scope: ["win_dc"],
        error: null,
      };
      ruleRuns.unshift(run);
      return json(run);
    }
    if (/\/api\/rules\/[^/]+$/.test(url) && method === "GET") {
      const id = url.split("/api/rules/")[1] ?? "";
      const r = rules.find((x) => x.rule_id === id);
      return r
        ? json({ ...r, yaml: "title: <b>not markup</b>\n" })
        : json({ detail: "No such rule" }, 404);
    }
    if (url.endsWith("/api/providers") && method === "GET") return json(providers);
    if (url.endsWith("/api/providers") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const cloud = String(body.base_url).startsWith("https://");
      if (cloud && !body.acknowledge_cloud)
        return json({ detail: "This URL is a cloud provider.", code: "cloud_ack_required" }, 409);
      const created = {
        provider_id: `p${providers.length + 1}`,
        name: body.name,
        kind: "openai_compat",
        base_url: body.base_url,
        model: body.model ?? "",
        enabled: false,
        has_api_key: Boolean(body.api_key),
        locality: cloud ? "cloud" : "local",
        host_found: true,
      };
      providers.push(created);
      return json(created, 201);
    }
    if (/\/api\/providers\/[^/]+\/test$/.test(url))
      return json({ ok: true, detail: "Reachable", models: ["llama3.1:8b", "qwen2.5:7b"] });
    if (/\/api\/providers\/[^/]+$/.test(url) && method === "PATCH") {
      const id = url.split("/api/providers/")[1];
      const p = providers.find((x) => x.provider_id === id);
      Object.assign(p ?? {}, JSON.parse(String(init?.body ?? "{}")));
      return json(p);
    }
    if (/\/api\/providers\/[^/]+$/.test(url) && method === "DELETE") {
      const id = url.split("/api/providers/")[1];
      providers.splice(
        providers.findIndex((x) => x.provider_id === id),
        1,
      );
      return new Response(null, { status: 204 });
    }
    if (url.endsWith("/api/explain")) {
      const body = JSON.parse(String(init?.body ?? "{}")) as { event_ids: string[] };
      const first = body.event_ids[0] ?? "";
      return json({
        claims: [
          { text: "Repeated failed logins from one address.", event_ids: [first], verified: true },
          {
            text: "The <b>attacker</b> also tried root.",
            event_ids: ["99999999-0000-4000-8000-000000000000"],
            verified: false,
          },
        ],
        citation_check: "fail",
        call_id: "c1",
        events_sent: body.event_ids,
        not_found: 0,
        sources: ["linux_sshd"],
        provider: {
          provider_id: "p1",
          name: "Local Ollama",
          model: "llama3.1:8b",
          locality: "local",
        },
      });
    }
    if (url.endsWith("/api/ask/providers"))
      return json([
        { provider_id: "p1", name: "Local Ollama", model: "llama3.1:8b", locality: "local" },
        { provider_id: "p2", name: "Cloud", model: "gpt-x", locality: "cloud" },
      ]);
    if (url.endsWith("/api/ask")) {
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        question: string;
        provider_id: string;
        history: unknown[];
      };
      if (body.question === "while the model is busy" && !askBusySeen) {
        askBusySeen = true;
        return json(
          {
            detail: "The model was busy for 120 seconds. Try again in a moment.",
            code: "provider_busy",
          },
          503,
        );
      }
      if (body.provider_id === "p2")
        return json(
          {
            detail:
              "This provider is a cloud service and the search includes local-only sources: linux_sshd",
            code: "classification_blocked",
          },
          403,
        );
      const n = body.history.length + 1;
      return json({
        sql: `SELECT src_endpoint_ip, count(*) AS failures FROM events GROUP BY 1 -- turn ${n}`,
        explanation: "<b>Failed</b> logins grouped by source IP.",
        assumptions: ["Failed means status_id = 2"],
        check: "ok",
        check_detail: null,
        attempts: 1,
        provider: {
          provider_id: "p1",
          name: "Local Ollama",
          model: "llama3.1:8b",
          locality: "local",
        },
        call_ids: ["c1"],
      });
    }
    if (url.endsWith("/api/schema/columns"))
      return json(
        ["time", "source_id", "device_hostname", "message", "raw", "event_id"].map((name) => ({
          name,
          type: name === "time" ? "timestamptz" : "string",
          group: "core",
          description: "",
          nullable: true,
        })),
      );
    if (url.endsWith("/api/sources/settings")) return json({ allowed_roots: ["/logs"] });
    if (url.endsWith("/api/sources/discover") && method === "POST") {
      const { path } = JSON.parse(String(init?.body)) as { path: string };
      if (!path.startsWith("/logs"))
        return json({ detail: "Path is outside the allowed roots: " + path }, 400);
      return json({
        root: path,
        truncated: false,
        skipped: { compressed: 2 },
        candidates: [
          {
            path,
            glob: "*/sshd.log",
            files: 2,
            bytes: 9000,
            hosts: ["192.0.2.10", "192.0.2.11"],
            kind: "text",
            sniff: {
              lines: 120,
              envelope: { "3164": 120 },
              app_names: [["sshd", 120]],
              formats: { plain: 120 },
              format: "plain",
            },
            matches: [
              {
                template_id: "linux_sshd",
                name: "Linux sshd authentication",
                confidence: 1,
                min_confidence: 0.9,
                passes: true,
                parse_rate: 0.985,
                coverage: 11.5,
              },
            ],
            preview: ["<38>Oct  9 20:41:15 bastion sshd[1]: Accepted publickey for alice"],
            extra_matches: 0,
          },
          {
            path,
            glob: "notes.txt",
            files: 1,
            bytes: 10,
            hosts: [],
            kind: "text",
            sniff: {
              lines: 1,
              envelope: { none: 1 },
              app_names: [],
              formats: { plain: 1 },
              format: "plain",
            },
            matches: [],
            preview: ["<img src=x onerror=alert(1)>"],
            extra_matches: 2,
          },
        ],
      });
    }
    if (url.endsWith("/api/sources/watches")) return json(watches);
    if (/\/api\/sources\/[^/]+\/watch$/.test(url) && method === "PUT") {
      const id = decodeURIComponent(url.split("/api/sources/")[1]?.split("/")[0] ?? "");
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        quiet_after_s: number | null;
        target_ids: string[];
      };
      const s = sources.find((x) => x.source_id === id);
      if (!s) return json({ detail: "No such source", code: "not_found" }, 404);
      const at = watches.findIndex((w) => w.source_id === id);
      if (at >= 0) watches.splice(at, 1);
      if (body.quiet_after_s === null) {
        Object.assign(s, { quiet: null });
        return json(null);
      }
      const quiet = {
        quiet_after_s: body.quiet_after_s,
        state: "ok",
        quiet_since: null,
        last_seen: "2026-10-10T12:00:00+00:00",
      };
      Object.assign(s, { quiet });
      const w = {
        ...quiet,
        source_id: id,
        target_ids: body.target_ids,
        updated_at: "2026-10-10T12:00:00+00:00",
        updated_by: "u1",
      };
      watches.push(w);
      return json(w);
    }
    if (url.endsWith("/api/sources") && method === "GET") return json(sources);
    if (/\/api\/sources\/[^/]+$/.test(url) && method === "PATCH") {
      const id = decodeURIComponent(url.split("/api/sources/")[1] ?? "");
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const s = sources.find((x) => x.source_id === id);
      if (!s) return json({ detail: "No such source", code: "not_found" }, 404);
      if ("classification" in body) Object.assign(s, { classification: body.classification });
      if ("template_id" in body) Object.assign(s, { template_id: body.template_id });
      if ("timezone" in body) Object.assign(s, { timezone: body.timezone });
      if ("retention_days" in body) Object.assign(s, { retention_days: body.retention_days });
      if ("connector" in body) {
        const kind = (s as { kind?: string }).kind ?? "file";
        const current = (s as Record<string, unknown>)[kind] as Record<string, unknown>;
        Object.assign(s, { [kind]: { ...current, ...(body.connector as object) } });
      }
      return json(s);
    }
    if (url.endsWith("/api/sources/loki/test")) {
      const body = JSON.parse(String(init?.body ?? "{}")) as { query: string };
      if (!body.query.startsWith("{"))
        return json({ detail: "Start with a label selector", code: "param_invalid" }, 400);
      return json({
        lines: 42,
        stream_count: 1,
        groups: [{ labels: { job: "syslog", host: "fw01" }, streams: 1 }],
        ignored_labels: [],
        newest: "2026-10-12T11:59:00+00:00",
      });
    }
    if (url.endsWith("/api/sources/api/test")) {
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        kind: string;
        credentials: { certificate_pem?: string };
      };
      if (body.kind === "m365")
        return json({
          feeds: {
            "Management Activity API":
              "ok: no subscription yet for Audit.General; it starts when the source is added",
            "Graph signins": "Sign-in logs need Entra ID P1 or P2 in this tenant",
          },
          thumbprint: body.credentials.certificate_pem
            ? "A1B2C3D4E5F60718293A4B5C6D7E8F9012345678"
            : null,
        });
      return json({ feeds: { usage: "ok" }, thumbprint: null });
    }
    if (url.includes("/api/sources/") && url.endsWith("/credentials") && method === "PUT")
      return new Response(null, { status: 204 });
    if (url.endsWith("/api/sources") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        path: string;
        kind?: string;
        credentials?: unknown;
      };
      delete body.credentials; // write-only: the server never returns it
      if (
        !["loki", "otlp", "m365", "anthropic", "syslog"].includes(body.kind ?? "") &&
        !body.path.startsWith("/logs")
      )
        return json(
          { detail: `Path is outside the allowed roots: ${body.path}`, code: "source_rejected" },
          400,
        );
      const created = {
        ...SOURCE,
        ...body,
        status: {
          ...SOURCE.status,
          state: "waiting",
          files: 0,
          listener:
            body.kind === "syslog"
              ? {
                  protocol: "tls",
                  port: 6514,
                  listening: true,
                  received: 1200,
                  dropped_not_allowed: 4,
                  dropped_full: 0,
                  connections: 1,
                  last_message_at: "2026-10-16T20:00:00Z",
                  senders: [
                    { address: "192.168.1.1", count: 1200, last_seen: null, allowed: true },
                    { address: "203.0.113.9", count: 4, last_seen: null, allowed: false },
                  ],
                }
              : null,
        },
      };
      sources.push(created);
      if (body.kind === "otlp")
        return json({ ...created, otlp_token: "rmt_test_token_value" }, 201);
      return json(created, 201);
    }
    if (url.includes("/api/sources/") && method === "DELETE") {
      const id = decodeURIComponent(url.split("/api/sources/")[1] ?? "");
      sources.splice(
        sources.findIndex((s) => s.source_id === id),
        1,
      );
      return new Response(null, { status: 204 });
    }
    if (url.endsWith("/api/auth/state"))
      return json({
        mode: state.mode,
        user: state.mode === "login" && state.signedIn ? user : null,
        csrf_token: state.signedIn ? "csrf-1" : null,
        sso: state.sso ? { label: state.sso, passwords_admins_only: true } : null,
      });
    if (url.endsWith("/api/auth/sso/start")) {
      if (!state.sso)
        return json({ detail: "Single sign-on is not turned on", code: "sso_refused" }, 400);
      return json({ url: "https://login.example.test/authorize?state=s" });
    }
    if (url.endsWith("/api/setup")) {
      const body = JSON.parse(String(init?.body ?? "{}")) as { token: string };
      if (body.token !== "good-token")
        return json({ detail: "bad link", code: "setup_invalid" }, 403);
      Object.assign(state, { mode: "login", signedIn: true });
      return json({ user, csrf_token: "csrf-1" }, 201);
    }
    if (url.endsWith("/api/auth/login")) {
      const body = JSON.parse(String(init?.body ?? "{}")) as { password: string };
      if (body.password !== "right password")
        return json({ detail: "Wrong username or password", code: "login_failed" }, 401);
      state.signedIn = true;
      return json({ user, csrf_token: "csrf-1" });
    }
    if (url.endsWith("/api/auth/logout")) {
      if (state.logoutFails) return json({ detail: "boom", code: "internal" }, 500);
      state.signedIn = false;
      return new Response(null, { status: 204 });
    }
    if (url.endsWith("/api/meta"))
      return json({
        product_name: productName,
        version: "0.0.1",
        ocsf_version: "1.3.0",
        schema_version: 1,
      });
    if (url.endsWith("/api/query/export"))
      return new Response("time,message\r\n", {
        status: 200,
        headers: { "Content-Type": "text/csv" },
      });
    if (url.endsWith("/api/query")) {
      const body = JSON.parse(String(init?.body ?? "{}")) as { sql: string };
      if (/DROP/i.test(body.sql))
        return json(
          {
            detail: "Statement not allowed: only SELECT or WITH ... SELECT can run",
            code: "query_rejected",
          },
          400,
        );
      if (body.sql.includes("AS last_event"))
        return json(
          result({
            columns: ["source_id", "events", "last_event"],
            rows: [["linux_sshd", 1234, "2026-10-10T17:59:01+00:00"]],
          }),
        );
      if (body.sql.includes("GROUP BY source_id"))
        return json(
          result({
            columns: ["source_id", "events"],
            rows: [
              ["linux_sshd", 69],
              ["paloalto_traffic", 32],
            ],
          }),
        );
      if (body.sql.includes("WHERE event_id =")) return json(result(FULL_EVENT));
      if (body.sql.startsWith('SELECT count("src_endpoint_ip")'))
        return json(result({ columns: ["src_endpoint_ip"], rows: [[0]] }));
      if (body.sql.startsWith("SELECT event_id, raw FROM events"))
        return json(
          result({ columns: ["event_id", "raw"], rows: [[ID, FULL_EVENT.rows[0]?.[6] ?? ""]] }),
        );
      return json(result(RESULTS));
    }
    return json({ status: "ok" });
  });
}
