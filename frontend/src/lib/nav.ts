import type { PageId } from "@/lib/route";

export interface NavItem {
  id: string;
  label: string;
  ready: boolean;
  page?: PageId;
  adminOnly?: boolean;
  /** Admins and auditors (SPEC 3.6). */
  auditOnly?: boolean;
  /** Other words the command palette matches, including flavor names (CLAUDE.md rule 12). */
  aliases?: string[];
  /** Tabs of the page, listed under it in the left nav (URL `#id`). */
  sections?: NavSection[];
}

export interface NavSection {
  id: string;
  label: string;
  adminOnly?: boolean;
}

/** Sections this user can open (the page applies the same rule to its tabs). */
export function visibleSections(item: NavItem, isAdmin: boolean): NavSection[] {
  return (item.sections ?? []).filter((s) => isAdmin || !s.adminOnly);
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

// Plain labels only (CLAUDE.md rule 12). An area is one page of the rail (ADR-0052 section
// 3.2); its tabs sit in the page header, and the rail lists them under the current page only
// (D268), from the same list. Each tab is a page, or a page's tab (`tab`).
export interface AreaTab {
  label: string;
  page: PageId;
  tab?: string;
  adminOnly?: boolean;
  /** Only for those who may ask a model (admins and analysts, not auditors). */
  askOnly?: boolean;
  /** Only for those who may run a search (an Auditor only when Auditor SQL is on, D220). */
  sqlOnly?: boolean;
  aliases?: string[];
  /** A view of the page, opened from its Views menu: not a tab of the tab strip. */
  view?: boolean;
}

/** The Views of Logs: Microsoft 365 has no area of its own (ADR-0052 section 3.3). */
export const LOGS_VIEWS: { label: string; tab: string; aliases: string[] }[] = [
  {
    label: "Microsoft 365 sign-ins",
    tab: "sign-ins",
    aliases: ["m365", "office 365", "entra", "logins", "failed sign-ins"],
  },
  {
    label: "Microsoft 365 mail",
    tab: "mail",
    aliases: ["exchange", "inbox rules", "forwarding", "dlp"],
  },
  {
    label: "Microsoft 365 admin",
    tab: "admin",
    aliases: ["role grants", "conditional access", "consents", "app registrations", "sharepoint"],
  },
];

export interface Area {
  id: string;
  label: string;
  tabs: AreaTab[];
  aliases?: string[];
}

export const AREAS: Area[] = [
  // First, and the landing page when the viewer has a panel (ADR-0031).
  { id: "dashboard", label: "Dashboard", tabs: [{ label: "Dashboard", page: "dashboard" }] },
  {
    id: "alerts",
    label: "Alerts",
    aliases: ["inbox", "queue", "close", "needs attention", "mutes", "detections", "detect"],
    tabs: [
      // Open, Closed, and Muted are the Queue's State filter (ADR-0052 section 3.3).
      { label: "Queue", page: "alerts" },
      {
        label: "Handling",
        page: "handling",
        aliases: ["alert metrics", "time to close", "overdue alerts"],
      },
      { label: "Rules", page: "rules", aliases: ["detection rules", "sigma"] },
      { label: "Schedules", page: "schedules", aliases: ["scheduled searches"] },
    ],
  },
  {
    // One name per thing (D206): Logs is the manual search; saved searches are its tab.
    id: "logs",
    label: "Logs",
    aliases: ["search", "events", "query", "sql", "filters", "simple search"],
    tabs: [
      { label: "Search", page: "logs", sqlOnly: true },
      { label: "Saved searches", page: "saved", aliases: ["grimoire"] },
      // Shipped, tested queries (ADR-0033) that open in the SQL editor, so SQL access only.
      {
        label: "Library",
        page: "library",
        sqlOnly: true,
        aliases: ["query library", "packs", "shipped queries"],
      },
      // Views of Logs (ADR-0052 section 3.3): lists the server builds and runs on the
      // caller's own sources, so they need no SQL access. Opened from the Views menu.
      ...LOGS_VIEWS.map((v) => ({ ...v, page: "m365" as const, view: true })),
    ],
  },
  {
    id: "ask",
    label: "Ask AI",
    tabs: [{ label: "Ask AI", page: "ask", askOnly: true, aliases: ["ask", "seance"] }],
  },
  {
    id: "people",
    label: "People & devices",
    aliases: ["investigations", "entities", "risk", "investigator", "graph", "ai flow"],
    tabs: [{ label: "People & devices", page: "investigate" }],
  },
  {
    id: "ai",
    label: "AI usage",
    aliases: ["shadow ai", "claude usage", "dlp"],
    tabs: [
      { label: "Services", page: "ai", tab: "services" },
      { label: "People", page: "ai", tab: "people", aliases: ["claude usage"] },
      {
        label: "Inventory",
        page: "ai",
        tab: "inventory",
        aliases: ["ai inventory", "export ai inventory"],
      },
    ],
  },
  {
    id: "agents",
    label: "Agents",
    aliases: ["ai agents", "claude code", "sessions", "mcp servers"],
    tabs: [
      {
        label: "Sessions",
        page: "agents",
        tab: "sessions",
        aliases: ["agents overview", "failed tool calls"],
      },
      {
        label: "MCP servers",
        page: "agents",
        tab: "mcp",
        aliases: ["tools", "tool calls", "built-in tools"],
      },
      {
        label: "Accounts",
        page: "agents",
        tab: "accounts",
        aliases: ["claude accounts", "personal accounts", "account tiers"],
      },
    ],
  },
  {
    id: "health",
    label: "Health",
    aliases: [
      "overview",
      "status",
      "sensors",
      "collectors",
      "connectors health",
      "enrichment health",
      // The names of the tabs that are now Types of Sources and Collectors.
      "enrichment feeds",
      "endpoint agents",
      "watched devices",
      "alert delivery",
    ],
    tabs: [
      {
        label: "Sources",
        page: "health",
        tab: "sources",
        aliases: ["enrichment feeds", "enrichment health"],
      },
      // Log collectors, apart from the AI agents of the Agents page (F48).
      {
        label: "Collectors",
        page: "health",
        tab: "collectors",
        aliases: ["endpoint agents", "watched devices", "sensors"],
      },
      { label: "Delivery", page: "health", tab: "delivery", aliases: ["alert delivery"] },
    ],
  },
];

/** The rail (ADR-0052 section 3.2): three labeled groups of pages, then a pinned cluster at
 * the bottom (Health, and Settings, which keeps its own sub-nav). Only the current page lists
 * its tabs under it (D268); nothing else expands. Reports joins the pinned cluster when its
 * page exists. */
export interface RailGroup {
  id: string;
  /** Empty for the pinned cluster, which has no label. */
  label: string;
  areas: string[];
  pinned?: boolean;
}

export const RAIL_GROUPS: RailGroup[] = [
  { id: "monitor", label: "Monitor", areas: ["dashboard", "alerts"] },
  { id: "investigate", label: "Investigate", areas: ["logs", "ask", "people"] },
  { id: "ai", label: "AI", areas: ["ai", "agents"] },
  { id: "pinned", label: "", areas: ["health"], pinned: true },
];

/** One plain line per rail entry, its tooltip and accessible description (D268): what the
 * page is for, never its name, no flavor names, under about 50 characters. */
export const RAIL_DESCRIPTIONS: Record<string, string> = {
  dashboard: "What needs you today, at a glance",
  alerts: "Open alerts and the rules that raise them",
  logs: "Search every event",
  ask: "Ask about your logs in plain words",
  people: "Who and what is active, ranked by risk",
  ai: "Which AI services people use",
  agents: "AI agent sessions, MCP servers, and accounts",
  health: "Whether every source and collector is sending",
  settings: "Sources and app settings",
};

/** Tabs this user can open. */
export function visibleTabs(
  area: Area,
  isAdmin: boolean,
  canAsk = true,
  canRunSql = true,
): AreaTab[] {
  return area.tabs.filter(
    (t) =>
      !t.view && (isAdmin || !t.adminOnly) && (canAsk || !t.askOnly) && (canRunSql || !t.sqlOnly),
  );
}

/** The area a page belongs to, and which of its tabs is open. */
export function areaOf(page: PageId, tab: string): { area: Area; tab: AreaTab } | null {
  for (const area of AREAS) {
    const hits = area.tabs.filter((t) => t.page === page);
    if (hits.length === 0) continue;
    const open = hits.find((t) => (t.tab ?? "") === tab) ?? hits[0];
    return { area, tab: open as AreaTab };
  }
  return null;
}

/** Areas and their tabs as nav items, for the command palette ("Alerts › Rules"). */
function areaItems(): NavItem[] {
  // Logs and Ask AI are added by the palette, which knows who may search or ask.
  return AREAS.filter((a) => !a.tabs.some((t) => t.askOnly || t.sqlOnly)).flatMap((a): NavItem[] =>
    a.tabs.length === 1
      ? [{ id: a.id, label: a.label, ready: true, page: a.tabs[0]?.page, aliases: a.aliases }]
      : [
          {
            id: a.id,
            label: a.label,
            ready: true,
            page: a.tabs[0]?.page,
            aliases: a.aliases,
            sections: a.tabs
              .filter((t) => t.page === a.tabs[0]?.page && t.tab)
              .map((t) => ({ id: t.tab as string, label: t.label, adminOnly: t.adminOnly })),
          },
          ...a.tabs
            .filter((t) => t.page !== a.tabs[0]?.page && !t.askOnly)
            .map((t) => ({
              id: `${a.id}:${t.page}`,
              label: `${a.label} › ${t.label}`,
              ready: true,
              page: t.page,
              aliases: t.aliases,
              adminOnly: t.adminOnly,
            })),
        ],
  );
}

export const NAV_GROUPS: NavGroup[] = [{ label: "", items: areaItems() }];

// Admin and setup pages live in the Settings area, with their own sub-nav, so the main
// rail holds only daily work. URLs are unchanged. Ordered as a new install sets up:
// start, data in, who can see it, AI, where alerts go, and the record of it all.
export const SETTINGS_GROUPS: NavGroup[] = [
  {
    label: "Start here",
    items: [
      {
        id: "setup",
        label: "Setup checklist",
        ready: true,
        page: "setup",
        adminOnly: true,
        aliases: ["getting started", "setup", "checklist", "onboarding"],
      },
    ],
  },
  {
    label: "Data",
    items: [
      {
        id: "sources",
        label: "Sources and connectors",
        ready: true,
        page: "sources",
        aliases: ["sources", "connectors", "microsoft 365", "m365", "loki", "otlp"],
      },
      {
        id: "templates",
        label: "Templates",
        ready: true,
        page: "templates",
        adminOnly: true,
        aliases: ["parsers", "ossuary"],
      },
      {
        id: "enrichment",
        label: "Enrichment",
        ready: true,
        page: "enrichment",
        adminOnly: true,
        aliases: [
          "geoip",
          "geo ip",
          "asn",
          "country",
          "location",
          "db-ip",
          "maxmind",
          "approved countries",
          "internal networks",
          "egress",
        ],
      },
      {
        id: "identities",
        label: "Identities",
        ready: true,
        page: "identities",
        adminOnly: true,
        aliases: ["aliases", "duplicate names", "people", "organization domains"],
      },
    ],
  },
  {
    label: "Access",
    items: [
      { id: "users", label: "Users and access", ready: true, page: "users", adminOnly: true },
      {
        id: "sso",
        label: "Single sign-on",
        ready: true,
        page: "sso",
        adminOnly: true,
        aliases: ["sso", "oidc", "entra", "azure ad", "openid connect", "microsoft sign-in"],
      },
    ],
  },
  {
    label: "AI",
    items: [
      {
        id: "providers",
        label: "AI providers",
        ready: true,
        page: "providers",
        adminOnly: true,
      },
      {
        // What was AI usage > Review: what AI Watch alerts on, the MCP server rules, and
        // the catalog of AI services. Reviewing itself is the Inventory's Status filter.
        id: "aisettings",
        label: "AI watch and catalog",
        ready: true,
        page: "aisettings",
        adminOnly: true,
        aliases: ["ai watch", "mcp rules", "mcp server rules", "ai service catalog", "review"],
      },
      {
        id: "plugins",
        label: "Claude plugins",
        ready: true,
        page: "plugins",
        adminOnly: true,
        aliases: ["hooks plugin", "plugin download", "deployment tokens", "ingest tokens"],
      },
      {
        id: "mcp",
        label: "MCP server",
        ready: true,
        page: "mcp",
        adminOnly: true,
        aliases: ["model context protocol", "claude desktop", "ai assistant", "claude code"],
      },
    ],
  },
  {
    label: "Alerts",
    items: [
      {
        id: "targets",
        label: "Alert targets",
        ready: true,
        page: "targets",
        adminOnly: true,
        aliases: ["teams", "slack", "email", "webhook"],
      },
    ],
  },
  {
    // Settings > System (ADR-0052 section 3.3): Backups, Page rollups, and Speed, which were
    // Health tabs. Administrators only (owner, 2026-11-13).
    label: "System",
    items: [
      {
        id: "system",
        label: "System",
        ready: true,
        page: "system",
        adminOnly: true,
        aliases: [
          "backups",
          "backup status",
          "restore",
          "page rollups",
          "rollup status",
          "speed",
          "page speed",
          "slow pages",
          "p95",
        ],
      },
    ],
  },
  {
    label: "Records",
    items: [
      {
        id: "audit",
        label: "Audit log",
        ready: true,
        page: "audit",
        auditOnly: true,
        aliases: ["integrity", "tamper check", "hash chain", "seal"],
      },
      {
        id: "about",
        label: "About and licenses",
        ready: true,
        page: "about",
        aliases: ["licenses", "attribution", "db-ip", "credits", "version"],
      },
    ],
  },
];

export const SETTINGS_IDS = new Set(SETTINGS_GROUPS.flatMap((g) => g.items.map((i) => i.id)));

function allowed(i: NavItem, isAdmin: boolean, canAudit: boolean): boolean {
  return (isAdmin || !i.adminOnly) && (canAudit || !i.auditOnly);
}

/** Settings groups with only the items this user can open; empty groups dropped. */
export function visibleSettings(isAdmin: boolean, canAudit: boolean): NavGroup[] {
  return SETTINGS_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((i) => i.ready && allowed(i, isAdmin, canAudit)),
  })).filter((g) => g.items.length > 0);
}

/** Pages a user with these rights can open. */
export function visibleNav(isAdmin: boolean, canAudit: boolean): NavItem[] {
  return [...NAV_GROUPS, ...SETTINGS_GROUPS]
    .flatMap((g) => g.items)
    .filter((i) => i.ready && i.page && allowed(i, isAdmin, canAudit));
}
