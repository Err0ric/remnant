import type { CSSProperties } from "react";

/** One column scheme for the People & devices tabs, so they line up when switching
 * (DESIGN.md 6.3, People & devices): the name 28% of the table, 440px from a 1780px
 * window, with no floor; the lead number (the score, or a username's attempts) at least
 * 160px, 190px from a 1780px window; the other columns an equal share of 62% each. Auto table layout keeps each one-line header as a minimum, so a narrow window
 * takes the room from the name first. `clamp()` is not used: a table cell ignores it. */
export const NAME_COL = "w-[28%] min-[1780px]:w-[440px]";
export const LEAD_COL = "min-w-[160px] w-[160px] min-[1780px]:w-[190px]";

/** The equal share of each of `n` remaining columns. */
export function restCol(n: number): CSSProperties {
  return { width: `${(62 / Math.max(1, n)).toFixed(3)}%` };
}
