/** Command palette items, matching, and the per-browser "recent" list (DESIGN.md 7). */

export type PaletteSection =
  | "Recent"
  | "Ask AI"
  | "Addresses"
  | "People"
  | "Hosts"
  | "AI services"
  | "Logs"
  | "Navigate"
  | "Actions"
  | "Saved searches"
  | "Sources";

export interface PaletteItem {
  /** Stable key, also stored in Recent: "nav:sources", "saved:<id>", "source:<id>". */
  key: string;
  section: Exclude<PaletteSection, "Recent">;
  label: string;
  hint?: string;
  /** Extra words that match, such as flavor names; never shown. */
  aliases?: string[];
  /** Matched by the server (entity lookup); shown whatever the words. */
  found?: boolean;
  /** Shown in the data font (addresses, hosts, sources). */
  mono?: boolean;
  run: () => void;
}

// Entities first (ADR-0038 edit 10): typing an address, a user, or a host is a jump to
// its page; then pages and the rest, so a page name still opens with Enter; "Search
// events for" (in Logs) is last.
export const SECTION_ORDER: PaletteSection[] = [
  "Recent",
  "Ask AI",
  "Addresses",
  "People",
  "Hosts",
  "AI services",
  "Navigate",
  "Actions",
  "Saved searches",
  "Sources",
  "Logs",
];
// A question typed in the top bar is offered to Ask first (owner, 2026-11-03).
const QUESTION_WORDS = new Set([
  "how",
  "what",
  "who",
  "when",
  "why",
  "which",
  "show",
  "list",
  "did",
]);

/** Text that reads as a question: more than one word, and it ends with "?" or starts
 * with a question word ("how", "show", "did", ...). */
export function looksLikeQuestion(text: string): boolean {
  const t = text.trim();
  if (!/\s/.test(t)) return false;
  const first = t.split(/\s+/)[0]?.toLowerCase() ?? "";
  return t.endsWith("?") || QUESTION_WORDS.has(first);
}

const PER_SECTION_IDLE = 6; // with no query, long lists show their first few
const RECENT_KEY = "palette-recent";
const RECENT_MAX = 5;

function fold(text: string): string {
  return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** Every word of the query must appear in the label, hint, or an alias. */
export function matches(item: PaletteItem, query: string): boolean {
  if (item.found) return true;
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const hay = fold([item.label, item.hint ?? "", ...(item.aliases ?? [])].join(" "));
  return words.every((w) => hay.includes(w));
}

export interface PaletteGroup {
  section: PaletteSection;
  items: PaletteItem[];
}

/** Groups in display order; Recent only when the query is empty. */
export function arrange(items: PaletteItem[], query: string, recent: string[]): PaletteGroup[] {
  const idle = !query.trim();
  const groups: PaletteGroup[] = [];
  if (idle) {
    const byKey = new Map(items.map((i) => [i.key, i]));
    const rec = recent.map((k) => byKey.get(k)).filter((i): i is PaletteItem => !!i);
    if (rec.length) groups.push({ section: "Recent", items: rec });
  }
  for (const section of SECTION_ORDER.slice(1)) {
    let list = items.filter((i) => i.section === section && matches(i, query));
    if (idle && (section === "Saved searches" || section === "Sources")) {
      list = list.slice(0, PER_SECTION_IDLE);
    }
    if (list.length) groups.push({ section, items: list });
  }
  return groups;
}

export function readRecent(): string[] {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
  } catch {
    return [];
  }
}

export function rememberRecent(key: string): void {
  const next = [key, ...readRecent().filter((k) => k !== key)].slice(0, RECENT_MAX);
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // Storage blocked: Recent just stays empty.
  }
}
