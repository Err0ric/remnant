import type { MouseEvent } from "react";
import { cn } from "@/lib/cn";
import { navigate, pathFor, type PageId } from "@/lib/route";

interface NavItem {
  id: string;
  label: string;
  ready: boolean;
  page?: PageId;
  adminOnly?: boolean;
  /** Admins and auditors (SPEC 3.6). */
  auditOnly?: boolean;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

// Plain labels only (CLAUDE.md rule 12). Items not built yet stay visible but inert.
const GROUPS: NavGroup[] = [
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
      { id: "saved", label: "Saved searches", ready: true, page: "saved" },
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
      { id: "templates", label: "Templates", ready: true, page: "templates", adminOnly: true },
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

interface SideNavProps {
  active: string;
  isAdmin: boolean;
  canAudit: boolean;
}

export function SideNav({ active, isAdmin, canAudit }: SideNavProps) {
  return (
    <nav aria-label="Primary" className="w-55 shrink-0 border-r border-border bg-nav px-2 py-3">
      {GROUPS.map((group) => (
        <div key={group.label} className="mb-3">
          <div className="px-2.5 py-1 text-xs text-text-muted">{group.label}</div>
          {group.items
            .filter((item) => (isAdmin || !item.adminOnly) && (canAudit || !item.auditOnly))
            .map((item) => (
              <a
                key={item.id}
                href={item.page ? pathFor(item.page) : undefined}
                onClick={(e: MouseEvent) => {
                  if (!item.page || e.metaKey || e.ctrlKey || e.shiftKey) return;
                  e.preventDefault();
                  navigate(item.page);
                }}
                aria-current={item.id === active ? "page" : undefined}
                aria-disabled={item.ready ? undefined : true}
                title={item.ready ? undefined : "Coming in a later release"}
                className={cn(
                  "flex items-center rounded px-2.5 py-1.5 text-base no-underline",
                  item.id === active
                    ? "bg-accent-subtle font-semibold text-accent-text"
                    : item.ready
                      ? "text-text hover:bg-surface-head"
                      : "cursor-default text-text-muted",
                )}
              >
                {item.ready ? (
                  item.label
                ) : (
                  <>
                    <span>{item.label}</span>
                    {/* Visible without hovering: these look like links otherwise. */}
                    <span className="ml-auto text-xs text-text-muted">Later</span>
                  </>
                )}
              </a>
            ))}
        </div>
      ))}
    </nav>
  );
}
