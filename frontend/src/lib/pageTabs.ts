import type { MouseEvent } from "react";
import { areaOf, visibleTabs, type Area, type AreaTab } from "@/lib/nav";
import {
  fragmentValues,
  navigate,
  navigateTab,
  pathFor,
  usePage,
  useSection,
  useTab,
  type PageId,
} from "@/lib/route";
import { useViewer } from "@/lib/viewer";

export interface PageTabs {
  page: PageId;
  place: { area: Area; tab: AreaTab } | null;
  /** The tabs the viewer may open, in the page's order; one or none means no tab bar. */
  tabs: AreaTab[];
  isOpen: (t: AreaTab) => boolean;
  href: (t: AreaTab) => string;
  onClick: (t: AreaTab) => (e: MouseEvent) => void;
}

export function tabKey(t: AreaTab): string {
  return `${t.page}:${t.tab ?? ""}`;
}

/** The open page's tabs: the one list the page header's tab bar and the rail's expanded
 * entry both draw (DESIGN.md 5), so the two never differ. A tab of the same page keeps the
 * page's time choice, which lives in the fragment (ADR-0052 section 3.7). */
export function usePageTabs(): PageTabs {
  const page = usePage();
  const tab = useTab();
  const frag = fragmentValues(useSection());
  const time = new URLSearchParams();
  for (const k of ["time", "from", "to"]) {
    const v = frag.get(k);
    if (v) time.set(k, v);
  }
  const keeps = (t: AreaTab) => t.page === page && t.tab !== undefined && time.toString() !== "";
  const { isAdmin, canAsk = true, canRunSql = true } = useViewer();
  const place = areaOf(page, tab);
  const tabs = place ? visibleTabs(place.area, isAdmin, canAsk, canRunSql) : [];
  return {
    page,
    place,
    tabs,
    isOpen: (t) => place !== null && tabKey(t) === tabKey(place.tab),
    href: (t) => pathFor(t.page, t.tab) + (keeps(t) ? `#${time.toString()}` : ""),
    onClick: (t) => (e) => {
      if (e.metaKey || e.ctrlKey || e.shiftKey) return;
      e.preventDefault();
      if (keeps(t) && t.tab) navigateTab(t.page, t.tab, time.toString());
      else navigate(t.page, t.tab);
    },
  };
}
