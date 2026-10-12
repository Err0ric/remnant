import type { MouseEvent } from "react";
import { cn } from "@/lib/cn";
import { NAV_GROUPS as GROUPS } from "@/lib/nav";
import { navigate, pathFor } from "@/lib/route";

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
