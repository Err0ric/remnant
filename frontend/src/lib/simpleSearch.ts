import type { CompiledSearch } from "./api";

/** Logs modes (D206): "simple" is Filters, "sql" is SQL. */
export type SearchTab = "simple" | "sql";

const TAB_KEY = "search-tab";

/** The mode last used in this browser; Filters the first time (ADR-0009 row 9). "ask",
 * kept by browsers from before Ask AI was its own page (D206), opens Filters. */
export function storedTab(): SearchTab {
  try {
    const v = window.localStorage.getItem(TAB_KEY);
    return v === "sql" ? "sql" : "simple";
  } catch {
    return "simple"; // storage blocked
  }
}

export function storeTab(tab: SearchTab): void {
  try {
    window.localStorage.setItem(TAB_KEY, tab);
  } catch {
    // storage blocked: the choice lasts for this visit only
  }
}

/** A Simple search term for one field value: `field:"value"`, or `-field:"value"`. */
export function filterTerm(field: string, value: string, exclude: boolean): string {
  const quoted = `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
  return `${exclude ? "-" : ""}${field}:${quoted}`;
}

/** Append a term to the search text, keeping what is there. */
export function addTerm(text: string, term: string): string {
  const t = text.trim();
  return t ? `${t} ${term}` : term;
}

function literal(v: string | number | boolean | null): string {
  if (v === null) return "NULL";
  if (typeof v === "number" || typeof v === "boolean") return String(v).toUpperCase();
  return `'${v.replace(/'/g, "''")}'`;
}

/**
 * The compiled SQL with its parameters written in as SQL literals, for the SQL editor and
 * for saving. The compiler emits `$pN` only as placeholders (never inside text), and
 * whatever the editor holds still runs through the server's guard.
 */
export function inlineParams(compiled: CompiledSearch): string {
  const names = Object.keys(compiled.params).sort((a, b) => b.length - a.length);
  let sql = compiled.sql;
  for (const name of names) {
    sql = sql.split(`$${name}`).join(literal(compiled.params[name] ?? null));
  }
  return sql;
}
