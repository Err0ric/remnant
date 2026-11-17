import type { MouseEvent } from "react";
import { Globe, Monitor, User, type LucideIcon } from "lucide-react";
import { Truncate } from "@/components/Truncate";
import { entityHref, openEntity } from "@/lib/entity";
import { usePins } from "@/lib/pins";
import { railFit, useWindowHeight } from "@/lib/railFit";
import { useRecentEntities, type RecentEntity, type RecentKind } from "@/lib/recentEntities";
import { useViewer } from "@/lib/viewer";

const ICONS: Record<RecentKind, LucideIcon> = { user: User, host: Monitor, ip: Globe };
const KIND_WORD: Record<RecentKind, string> = { user: "Person", host: "Host", ip: "Address" };

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
 * in the icon-only rail, and on short windows: five rows from 700px tall, three from 620px,
 * none below that, and higher with the current page's tab rows and Pinned above it
 * (`railFit`), so the rail never scrolls. Kept in this browser only. */
export function RecentNav({ tabRows = 0 }: { tabRows?: number }) {
  const { userId = "", canViewPeople = true } = useViewer();
  const items = useRecentEntities(userId, canViewPeople);
  const pinned = usePins().data?.length ?? 0;
  const fit = railFit(useWindowHeight(), tabRows, pinned).recent;
  if (!items.length || !fit) return null;
  return (
    <nav aria-label="Recent" className="mb-3 md:max-[1099px]:hidden">
      <div aria-hidden="true" className="px-2.5 pb-1 text-xs text-text-muted">
        Recent
      </div>
      <ul className="flex flex-col gap-px">
        {items.slice(0, fit).map((e) => {
          const Icon = ICONS[e.kind];
          return (
            <li key={`${e.kind}:${e.value}`}>
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
