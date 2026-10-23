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
// Ordered as a morning reads (ADR-0037 rows 1 to 3): the four daily places are top level,
// with no heading over a single item; Investigate and Detect stay groups. A group with an
// empty label has no heading. Settings sits at the bottom.
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "",
    items: [
      // First, and the landing page when the viewer has a panel (ADR-0031).
      { id: "dashboard", label: "Dashboard", ready: true, page: "dashboard" },
      {
        id: "alerts",
        label: "Alerts",
        ready: true,
        page: "alerts",
        aliases: ["inbox", "queue", "close", "needs attention", "mutes", "detections"],
      },
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
    label: "",
    items: [
      {
        id: "ai",
        label: "AI usage",
        ready: true,
        page: "ai",
        aliases: ["shadow ai", "mcp servers", "claude usage", "dlp", "ai agents"],
        sections: [
          { id: "services", label: "Services" },
          { id: "agents", label: "Agents" },
          { id: "mcp", label: "MCP servers" },
          { id: "people", label: "Claude usage" },
          { id: "settings", label: "Review and alerts", adminOnly: true },
        ],
      },
      {
        id: "health",
        label: "Health",
        ready: true,
        page: "health",
        aliases: [
          "overview",
          "status",
          "sensors",
          "endpoint agents",
          "collectors",
          "watched devices",
          "connectors health",
          "enrichment health",
        ],
        sections: [
          { id: "sources", label: "Sources" },
          { id: "enrichment", label: "Enrichment feeds" },
          // "Agents" alone is the AI agents tab; these are the log collectors (F48).
          { id: "agents", label: "Endpoint agents" },
          { id: "devices", label: "Watched devices" },
          { id: "alerts", label: "Alert delivery and schedules" },
        ],
      },
    ],
  },
  {
    label: "Detect",
    items: [
      { id: "rules", label: "Detection rules", ready: true, page: "rules" },
      { id: "schedules", label: "Schedules", ready: true, page: "schedules" },
    ],
  },
];

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
