import { useSyncExternalStore } from "react";

function subscribe(callback: () => void) {
  window.addEventListener("resize", callback);
  return () => window.removeEventListener("resize", callback);
}

/** The window's height in CSS px, following resizes. */
export function useWindowHeight(): number {
  return useSyncExternalStore(subscribe, () => window.innerHeight);
}

/** What a rail row above Recent or Pinned costs in window height (DESIGN.md 5): a pin, an
 * expanded tab row, or the empty Pinned line, and opening the Pinned region. */
export const ROW_STEP = 30;
export const REGION_STEP = 40;

/** How many rows of Recent or Pinned fit (DESIGN.md 5): five from 700px tall, three from
 * 620px, none below, each threshold raised by `above` px of rows that give way later, so
 * the rail never scrolls. */
export function fitRows(height: number, above: number): number {
  if (height >= 700 + above) return 5;
  if (height >= 620 + above) return 3;
  return 0;
}

/** Rows of Pinned (its empty line is one, two rows high as it wraps in the 208px rail) and
 * of Recent on a window `height` tall, with `tabRows` tab rows under the current page and
 * `pins` pins. Recent gives way first. */
export function railFit(
  height: number,
  tabRows: number,
  pins: number,
): { pinned: number; recent: number } {
  const tabs = tabRows * ROW_STEP;
  const pinned = Math.min(fitRows(height, tabs), Math.max(pins, 1));
  const high = pins ? pinned : 2 * pinned;
  const recent = fitRows(height, tabs + (pinned ? REGION_STEP + ROW_STEP * high : 0));
  return { pinned, recent };
}

/** The current page's tab rows on a window `height` tall: all of them, or none once the
 * pages and the tabs no longer fit (from 470px tall the pages alone fit, plus 30px a row).
 * They give way last, after Recent and Pinned, so the rail never scrolls. */
export function fitTabs(height: number, tabRows: number): number {
  return height >= 470 + tabRows * ROW_STEP ? tabRows : 0;
}
