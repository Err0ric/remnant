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

// Plain labels only (CLAUDE.md rule 12). The rail lists areas, one row each; an area's
// tabs sit in the page header (ADR-0038). Each tab is a page, or a page's tab (`tab`).
export interface AreaTab {
  label: string;
  page: PageId;
  tab?: string;
  adminOnly?: boolean;
  aliases?: string[];
}

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
      { label: "Open", page: "alerts", tab: "open" },
      { label: "Closed", page: "alerts", tab: "closed" },
      { label: "Muted", page: "alerts", tab: "muted" },
      { label: "Rules", page: "rules", aliases: ["detection rules", "sigma"] },
      { label: "Schedules", page: "schedules", aliases: ["scheduled searches"] },
    ],
  },
  {
    id: "investigate",
    label: "Investigate",
    tabs: [
      { label: "Search", page: "search" },
      {
        label: "People & devices",
        page: "investigate",
        aliases: ["investigations", "entities", "risk", "investigator", "graph", "ai flow"],
      },
      { label: "Saved searches", page: "saved", aliases: ["grimoire"] },
    ],
  },
  {
    id: "ai",
    label: "AI usage",
    aliases: ["shadow ai", "claude usage", "dlp"],
    tabs: [
      { label: "Services", page: "ai", tab: "services" },
      { label: "People", page: "ai", tab: "people", aliases: ["claude usage"] },
      { label: "Review", page: "ai", tab: "settings", adminOnly: true },
    ],
  },
  {
    id: "agents",
    label: "Agents",
    aliases: ["ai agents", "claude code", "sessions", "mcp servers"],
    tabs: [
      { label: "Sessions", page: "agents", tab: "agents" },
      { label: "MCP servers", page: "agents", tab: "mcp" },
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
    ],
    tabs: [
      { label: "Sources", page: "health", tab: "sources" },
      { label: "Enrichment feeds", page: "health", tab: "enrichment" },
      // "Agents" alone is the AI agents area; these are the log collectors (F48).
      { label: "Endpoint agents", page: "health", tab: "agents" },
      { label: "Watched devices", page: "health", tab: "devices" },
      { label: "Delivery", page: "health", tab: "alerts", aliases: ["alert delivery"] },
    ],
  },
];

/** Tabs this user can open. */
export function visibleTabs(area: Area, isAdmin: boolean): AreaTab[] {
  return area.tabs.filter((t) => isAdmin || !t.adminOnly);
}

/** The area a page belongs to, and which of its tabs is open. */
export function areaOf(page: PageId, tab: string): { area: Area; tab: AreaTab } | null {
  // Ask is a mode of Search (ADR-0008); /ask still opens it.
  if (page === "ask") return areaOf("search", tab);
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
  return AREAS.flatMap((a): NavItem[] =>
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
            .filter((t) => t.page !== a.tabs[0]?.page)
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
        aliases: ["geoip", "geo ip", "asn", "country", "location", "db-ip", "maxmind"],
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
