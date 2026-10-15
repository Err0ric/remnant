import type { MouseEvent } from "react";
import { cn } from "@/lib/cn";
import { visibleSettings } from "@/lib/nav";
import { navigate, pathFor } from "@/lib/route";

interface SettingsNavProps {
  active: string;
  isAdmin: boolean;
  canAudit: boolean;
}

/** Sub-nav of the Settings area: a column on wide screens, a scrolling row on phones. */
export function SettingsNav({ active, isAdmin, canAudit }: SettingsNavProps) {
  return (
    <nav
      aria-label="Settings"
      className="flex shrink-0 gap-4 overflow-x-auto border-b border-border bg-surface px-3 py-2 md:w-48 md:flex-col md:gap-3 md:overflow-visible md:border-b-0 md:border-r md:py-4"
    >
      <div className="hidden px-2.5 text-sm font-semibold md:block">Settings</div>
      {visibleSettings(isAdmin, canAudit).map((group) => (
        <div
          key={group.label}
          className="flex shrink-0 items-center gap-1 md:flex-col md:items-stretch"
        >
          <div className="hidden px-2.5 py-1 text-xs text-text-muted md:block">{group.label}</div>
          {group.items.map((item) => (
            <a
              key={item.id}
              href={item.page ? pathFor(item.page) : undefined}
              onClick={(e: MouseEvent) => {
                if (!item.page || e.metaKey || e.ctrlKey || e.shiftKey) return;
                e.preventDefault();
                navigate(item.page);
              }}
              aria-current={item.id === active ? "page" : undefined}
              className={cn(
                "whitespace-nowrap rounded px-2.5 py-1.5 text-sm no-underline",
                item.id === active
                  ? "bg-accent-subtle font-semibold text-accent-text"
                  : "text-text hover:bg-surface-head",
              )}
            >
              {item.label}
            </a>
          ))}
        </div>
      ))}
    </nav>
  );
}
