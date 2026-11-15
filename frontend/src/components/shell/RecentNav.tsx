import type { MouseEvent } from "react";
import { Globe, Monitor, User, type LucideIcon } from "lucide-react";
import { Truncate } from "@/components/Truncate";
import { cn } from "@/lib/cn";
import { entityHref, openEntity } from "@/lib/entity";
import { usePins } from "@/lib/pins";
import { useRecentEntities, type RecentEntity, type RecentKind } from "@/lib/recentEntities";
import { useViewer } from "@/lib/viewer";

const ICONS: Record<RecentKind, LucideIcon> = { user: User, host: Monitor, ip: Globe };
const KIND_WORD: Record<RecentKind, string> = { user: "Person", host: "Host", ip: "Address" };

/** Where Recent gives way on a short window, by how many pins sit above it (D259): its
 * fourth and fifth rows, then all of it. Recent goes first, so Pinned keeps its rows. */
const FIT: [string, string][] = [
  ["[@media(max-height:699px)]:hidden", "[@media(max-height:619px)]:hidden"],
  ["[@media(max-height:769px)]:hidden", "[@media(max-height:689px)]:hidden"],
  ["[@media(max-height:799px)]:hidden", "[@media(max-height:719px)]:hidden"],
  ["[@media(max-height:829px)]:hidden", "[@media(max-height:749px)]:hidden"],
  ["[@media(max-height:859px)]:hidden", "[@media(max-height:779px)]:hidden"],
  ["[@media(max-height:889px)]:hidden", "[@media(max-height:809px)]:hidden"],
];

function open(e: RecentEntity) {
  return (ev: MouseEvent) => {
    if (ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
    ev.preventDefault();
    openEntity(e);
  };
}

/** The rail's Recent (D258, DESIGN.md 5): the last five entities the viewer opened, newest
 * first, under the page groups. Its own labelled region, not part of the Primary nav: these
 * are not pages, so the rows are 400 weight in the secondary text color. Hidden when empty,
 * in the icon-only rail, and on short windows: with no pins five rows from 700px tall, three
 * from 620px, none below that, and higher with pins above it (FIT), so the rail never
 * scrolls. Kept in this browser only. */
export function RecentNav() {
  const { userId = "", canViewPeople = true } = useViewer();
  const items = useRecentEntities(userId, canViewPeople);
  const pinned = usePins().data?.length ?? 0;
  const [rows, all] = FIT[Math.min(pinned, FIT.length - 1)] ?? ["", ""];
  if (!items.length) return null;
  return (
    <nav aria-label="Recent" className={cn("mb-3 md:max-[1099px]:hidden", all)}>
      <div aria-hidden="true" className="px-2.5 pb-1 text-xs text-text-muted">
        Recent
      </div>
      <ul className="flex flex-col gap-px">
        {items.map((e, i) => {
          const Icon = ICONS[e.kind];
          return (
            <li key={`${e.kind}:${e.value}`} className={cn(i >= 3 && rows)}>
              <a
                href={entityHref(e)}
                onClick={open(e)}
                title={`${KIND_WORD[e.kind]}: ${e.value}`}
                className="flex h-row-rail items-center gap-2.5 rounded px-2.5 text-sm font-normal text-text-secondary no-underline hover:bg-surface-head hover:text-text"
              >
                <Icon size={14} aria-hidden className="shrink-0" />
                <Truncate
                  value={e.value}
                  kind={e.kind === "user" && e.value.includes("@") ? "email" : "name"}
                  inLink
                  className="min-w-0 font-mono"
                />
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
