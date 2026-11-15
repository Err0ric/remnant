import type { MouseEvent } from "react";
import { LayoutGrid, Search, type LucideIcon } from "lucide-react";
import { Truncate } from "@/components/Truncate";
import { rememberDashboard } from "@/features/dashboard/choice";
import type { Pin } from "@/lib/api";
import { cn } from "@/lib/cn";
import { targetSection, usePins, usePinsFollowTargets } from "@/lib/pins";
import { navigate, pathFor } from "@/lib/route";

const ICONS: Record<Pin["kind"], LucideIcon> = { search: Search, dashboard: LayoutGrid };
const KIND_WORD: Record<Pin["kind"], string> = { search: "Saved search", dashboard: "Dashboard" };

/** Each pin's own address: the page opens its target from it, in a new tab too. */
function section(p: Pin): string {
  return targetSection(p.kind === "search" ? "open" : "board", p.id);
}

function href(p: Pin): string {
  return `${pathFor(p.kind === "search" ? "saved" : "dashboard")}#${section(p)}`;
}

function open(p: Pin) {
  return (ev: MouseEvent) => {
    if (ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
    ev.preventDefault();
    if (p.kind === "dashboard") rememberDashboard(p.id);
    navigate(p.kind === "search" ? "saved" : "dashboard", section(p));
  };
}

/** The rail's Pinned (D259, DESIGN.md 5): the viewer's pinned saved searches and dashboards,
 * oldest first, above Recent. Its own labelled region with Recent's row anatomy, not part of
 * the Primary nav. Hidden when empty and in the icon-only rail. Recent gives way first on a
 * short window; then Pinned shows three rows below 700px tall and none below 620px. */
export function PinnedNav() {
  const pins = usePins();
  usePinsFollowTargets();
  const items = pins.data ?? [];
  if (!items.length) return null;
  return (
    <nav
      aria-label="Pinned"
      className="mb-3 md:max-[1099px]:hidden [@media(max-height:619px)]:hidden"
    >
      <div aria-hidden="true" className="px-2.5 pb-1 text-xs text-text-muted">
        Pinned
      </div>
      <ul className="flex flex-col gap-px">
        {items.map((p, i) => {
          const Icon = ICONS[p.kind];
          return (
            <li
              key={`${p.kind}:${p.id}`}
              className={cn(i >= 3 && "[@media(max-height:699px)]:hidden")}
            >
              <a
                href={href(p)}
                onClick={open(p)}
                title={`${KIND_WORD[p.kind]}: ${p.name}`}
                className="flex h-row-rail items-center gap-2.5 rounded px-2.5 text-sm font-normal text-text-secondary no-underline hover:bg-surface-head hover:text-text"
              >
                <Icon size={14} aria-hidden className="shrink-0" />
                <Truncate value={p.name} kind="name" inLink className="min-w-0" />
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
