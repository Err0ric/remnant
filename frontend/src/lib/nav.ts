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

// Plain labels only (CLAUDE.md rule 12). Items not built yet stay visible but inert.
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "General",
    items: [
      { id: "overview", label: "Overview", ready: true, page: "overview" },
      {
        id: "health",
        label: "Health",
        ready: true,
        page: "health",
        aliases: ["status", "sensors", "agents", "watched devices", "connectors health"],
        sections: [
          { id: "sources", label: "Sources" },
          { id: "connectors", label: "Connectors" },
          { id: "agents", label: "Agents" },
          { id: "devices", label: "Watched devices" },
          { id: "alerts", label: "Alerts and schedules" },
        ],
      },
      { id: "dashboard", label: "Dashboard", ready: true, page: "dashboard" },
    ],
  },
  {
    label: "Investigate",
    items: [
      { id: "search", label: "Search", ready: true, page: "search" },
      {
        id: "investigate",
        label: "Investigations",
        ready: true,
        page: "investigate",
        aliases: ["entities", "risk", "investigator", "graph", "ai flow"],
      },
      { id: "saved", label: "Saved searches", ready: true, page: "saved", aliases: ["grimoire"] },
    ],
  },
  {
    label: "Detect",
    items: [
      { id: "rules", label: "Detection rules", ready: true, page: "rules" },
      { id: "schedules", label: "Schedules", ready: true, page: "schedules" },
      {
        id: "ai",
        label: "AI usage",
        ready: true,
        page: "ai",
        aliases: ["shadow ai", "mcp servers", "claude usage", "dlp"],
        sections: [
          { id: "services", label: "Services" },
          { id: "agents", label: "Agents" },
          { id: "mcp", label: "MCP servers" },
          { id: "people", label: "Claude usage" },
          { id: "settings", label: "Review and alerts", adminOnly: true },
        ],
      },
    ],
  },
];

// Admin and setup pages live in the Settings area, with their own sub-nav, so the main
// rail holds only daily work. URLs are unchanged.
export const SETTINGS_GROUPS: NavGroup[] = [
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
    ],
  },
  {
    label: "Access",
    items: [
      { id: "users", label: "Users and access", ready: true, page: "users", adminOnly: true },
      {
        id: "identities",
        label: "Identities",
        ready: true,
        page: "identities",
        adminOnly: true,
        aliases: ["aliases", "duplicate names", "people", "organization domains"],
      },
      {
        id: "audit",
        label: "Audit log",
        ready: true,
        page: "audit",
        auditOnly: true,
        aliases: ["integrity", "tamper check", "hash chain", "seal"],
      },
    ],
  },
  {
    label: "Integrations",
    items: [
      {
        id: "providers",
        label: "AI providers",
        ready: true,
        page: "providers",
        adminOnly: true,
      },
      {
        id: "alerts",
        label: "Alert targets",
        ready: true,
        page: "alerts",
        adminOnly: true,
        aliases: ["teams", "slack", "email", "webhook"],
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
    label: "Help",
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
