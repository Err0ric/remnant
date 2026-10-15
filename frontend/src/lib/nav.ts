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
      { id: "audit", label: "Audit log", ready: true, page: "audit", auditOnly: true },
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
