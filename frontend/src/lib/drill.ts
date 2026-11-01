import { navigate } from "@/lib/route";
import { seedSearch } from "@/lib/searchSeed";
import { TIME_RANGES, type TimeRangeId } from "@/lib/search";

/**
 * Dashboard drill-through (ADR-0039): the server sends each number's query with `{from}`
 * and `{to}`; this fills them with the window's bounds and opens Search, which runs it
 * through the guard on the viewer's own sources like anything typed.
 */
export interface Drill {
  sql: string;
  from: string;
  to: string;
  /** "Dashboard > Identity > Failed sign-ins". */
  origin: string;
}

const SCROLL_KEY = "dashboard.scroll";

const iso = (s: string) => new Date(s).toISOString().replace(".000Z", "+00:00");

const when = (s: string) =>
  new Date(s).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

/** The query with the bounds filled in, as Search will show it. */
export function drillSql(d: Pick<Drill, "sql" | "from" | "to">): string {
  return d.sql.replaceAll("{from}", iso(d.from)).replaceAll("{to}", iso(d.to));
}

/** The query for Search: the window's bounds become {{start}} and {{end}}, filled from
 * Search's time range, so changing the range works and a saved copy does not freeze on
 * the Dashboard's dates (owner, 2026-10-31). */
export function placeholderSql(sql: string): string {
  return sql
    .replaceAll("TIMESTAMPTZ '{from}'", "{{start}}")
    .replaceAll("TIMESTAMPTZ '{to}'", "{{end}}")
    .replaceAll("{from}", iso(new Date(0).toISOString()))
    .replaceAll("{to}", iso(new Date().toISOString()));
}

/** The smallest Search range that covers `from`, so the query reads only those days. */
export function coveringRange(from: string, now: Date = new Date()): TimeRangeId {
  const back = now.getTime() - new Date(from).getTime();
  const fit = TIME_RANGES.find((r) => r.ms !== null && r.ms >= back);
  return fit?.id ?? "all";
}

export function openDrill(d: Drill): void {
  try {
    window.sessionStorage.setItem(SCROLL_KEY, String(Math.round(window.scrollY)));
  } catch {
    // Storage blocked: Back still returns to the Dashboard, at the top.
  }
  seedSearch({
    sql: placeholderSql(d.sql),
    range: coveringRange(d.from),
    window: { from: d.from, to: d.to },
    origin: `From ${d.origin}, ${when(d.from)} to ${when(d.to)}`,
  });
  navigate("search");
}

/** The scroll position the Dashboard left for Search, taken once. */
export function takeDashboardScroll(): number | null {
  try {
    const v = window.sessionStorage.getItem(SCROLL_KEY);
    window.sessionStorage.removeItem(SCROLL_KEY);
    return v === null ? null : Number(v);
  } catch {
    return null;
  }
}
