import type { Cell } from "@/lib/api";

export type PanelWidth = "third" | "half" | "full";
export type PanelView = "table" | "bars";

/** Columns a panel shows at each width before "more columns" (trial finding: no sideways
 * scrolling in narrow panels). */
export const COLUMNS_AT: Record<PanelWidth, number> = { third: 3, half: 5, full: 10 };

/** Grid spans: one column on phones, two on tablets, six from wide screens. */
export const SPAN: Record<PanelWidth, string> = {
  third: "md:col-span-1 xl:col-span-2",
  half: "md:col-span-1 xl:col-span-3",
  full: "md:col-span-2 xl:col-span-6",
};

export const WIDTH_LABEL: Record<PanelWidth, string> = {
  third: "1/3",
  half: "1/2",
  full: "Full",
};

export function cellText(v: Cell): string {
  if (v === null) return "·";
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}

function isCount(v: Cell): boolean {
  return typeof v === "number"
    ? Number.isFinite(v)
    : typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v);
}

export interface BarShape {
  label: number;
  value: number;
}

/** A summary result ("AI services last 24h": a name and a count per row) can be drawn as
 * bars: the last column that is a number in every row, and the first other column. */
export function barShape(columns: string[], rows: Cell[][]): BarShape | null {
  if (rows.length === 0 || columns.length < 2) return null;
  let value = -1;
  for (let j = columns.length - 1; j >= 0; j--) {
    if (rows.every((r) => isCount(r[j] ?? null))) {
      value = j;
      break;
    }
  }
  if (value < 0) return null;
  const label = columns.findIndex((_, j) => j !== value);
  return label < 0 ? null : { label, value };
}
