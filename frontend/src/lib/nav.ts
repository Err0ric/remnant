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
      { id: "investigations", label: "Investigations", ready: false },
      { id: "saved", label: "Saved searches", ready: true, page: "saved", aliases: ["grimoire"] },
    ],
  },
  {
    label: "Detect",
    items: [
      { id: "rules", label: "Detection rules", ready: true, page: "rules" },
      { id: "schedules", label: "Schedules", ready: true, page: "schedules" },
    ],
  },
  {
    label: "Configuration",
    items: [
      { id: "sources", label: "Sources", ready: true, page: "sources" },
      {
        id: "templates",
        label: "Templates",
        ready: true,
        page: "templates",
        adminOnly: true,
        aliases: ["parsers", "ossuary"],
      },
      { id: "users", label: "Users and access", ready: true, page: "users", adminOnly: true },
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
      },
      { id: "audit", label: "Audit log", ready: true, page: "audit", auditOnly: true },
    ],
  },
];

/** Pages a user with these rights can open. */
export function visibleNav(isAdmin: boolean, canAudit: boolean): NavItem[] {
  return NAV_GROUPS.flatMap((g) => g.items).filter(
    (i) => i.ready && i.page && (isAdmin || !i.adminOnly) && (canAudit || !i.auditOnly),
  );
}
