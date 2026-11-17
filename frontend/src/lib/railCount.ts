import { useEffect, useState, useSyncExternalStore } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

// A count's first read waits until the page's own requests are out.
const FIRST_READ_MS = 2500;
const EVERY_MS = 300_000;
/** A page answer this recent is the count's answer; the pages refresh theirs themselves. */
const PAGE_FRESH_MS = 90_000;

/** A count that follows a page's own data (`pageKey`) while a page shows it, and asks for
 * nothing then: while the page that loads that data is open, its answer is the only answer,
 * so the count never disagrees with the rows on screen (owner, 2026-11-16). Otherwise it asks a numbers-only count every five minutes, the first time
 * after the page's own requests (or at once with `immediate`, for a page that states the
 * number itself). Never loads the page's data itself. Keep `countKey` under `pageKey`: a
 * change that invalidates the page's data then refreshes the count at once, and page data
 * so invalidated is never the answer. Null while neither answer is known; `empty` when
 * the count failed and the page has none. */
export function useRailCount<P, C, R = number>(
  pageKey: string[],
  pageFn: () => Promise<P>,
  countKey: string[],
  countFn: () => Promise<C>,
  fromPage: (p: P) => R,
  fromCount: (c: C) => R,
  empty: R,
  immediate = false,
): R | null {
  const page = useQuery({ queryKey: pageKey, queryFn: pageFn, enabled: false });
  const client = useQueryClient();
  const subscribe = (cb: () => void) => client.getQueryCache().subscribe(cb);
  const invalidated = useSyncExternalStore(
    subscribe,
    () => client.getQueryState(pageKey)?.isInvalidated ?? false,
  );
  // The page that loads this data is open: something other than these disabled readers
  // keeps the query active.
  const open = useSyncExternalStore(
    subscribe,
    () => client.getQueryCache().find({ queryKey: pageKey, exact: true })?.isActive() ?? false,
  );
  const [now, setNow] = useState(() => Date.now());
  const [ready, setReady] = useState(immediate);
  useEffect(() => {
    const first = window.setTimeout(() => setReady(true), FIRST_READ_MS);
    const tick = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(tick);
    };
  }, []);
  const usable = page.data !== undefined && !invalidated;
  const pageFresh = usable && now - page.dataUpdatedAt < PAGE_FRESH_MS;
  const count = useQuery({
    queryKey: countKey,
    queryFn: countFn,
    // Not while a page is loading or has just loaded the same answer.
    enabled: (ready || immediate) && !open && !page.isFetching && !pageFresh,
    refetchInterval: EVERY_MS,
    staleTime: 60_000,
  });
  // The open page's answer, even while it refetches after a change: the rows show it too.
  if (open) return page.data === undefined ? null : fromPage(page.data);
  // Whichever answer is newer: the page's or the count.
  if (usable && page.data !== undefined && page.dataUpdatedAt >= count.dataUpdatedAt)
    return fromPage(page.data);
  if (count.data !== undefined) return fromCount(count.data);
  // An answer the page had before a change still stands until the new one is in.
  if (page.data !== undefined) return fromPage(page.data);
  return count.isError ? empty : null;
}
