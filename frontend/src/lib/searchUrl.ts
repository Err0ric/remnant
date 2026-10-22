import { TIME_RANGES, type TimeRangeId } from "@/lib/search";

/**
 * The Search page's state in its address (D90): each run records the tab, the query or the
 * open saved search, and the time range, so Back and Forward step through earlier searches
 * and the address can be bookmarked or shared. A shared address shows nothing the reader
 * could not search already: the server applies the reader's own source access to every run.
 *
 * The state lives in the fragment (`/search#tab=sql&q=...`), never the query string. Browsers
 * do not send a fragment to the server, so search text (user names, addresses, investigation
 * terms) stays out of reverse proxy and SSO access logs, which often feed back into the lake.
 */
export interface SearchUrlState {
  tab: "simple" | "sql";
  /** Simple text or SQL. Left out when longer than MAX_Q (the address stays usable). */
  q?: string;
  /** An open saved search, run as saved with these parameter values. */
  saved?: string;
  params?: Record<string, string>;
  range: TimeRangeId;
}

export const MAX_Q = 4000;
const RANGES = new Set<string>(TIME_RANGES.map((r) => r.id));
const ID = /^[a-z0-9_]{1,64}$/;

export function searchUrl(state: SearchUrlState): string {
  const p = new URLSearchParams();
  if (state.saved) {
    p.set("saved", state.saved);
    for (const [k, v] of Object.entries(state.params ?? {})) p.set(`p.${k}`, v);
  } else {
    p.set("tab", state.tab);
    if (state.q && state.q.length <= MAX_Q) p.set("q", state.q);
  }
  p.set("range", state.range);
  return `/search#${p.toString()}`;
}

/** Read the state from a fragment (`#tab=...`). An address from before the fragment change
 * (`/search?tab=...`) is read once and moved to the fragment, so it is not sent again. */
export function readSearchUrl(fragment: string = window.location.hash): SearchUrlState | null {
  if (fragment === window.location.hash && window.location.search) {
    const legacy = new URLSearchParams(window.location.search);
    if (["tab", "q", "saved", "range"].some((k) => legacy.has(k))) {
      window.history.replaceState(null, "", `${window.location.pathname}#${legacy.toString()}`);
      fragment = window.location.hash;
    }
  }
  const p = new URLSearchParams(fragment.replace(/^#/, ""));
  // Only a search fragment counts: another page's `#section` or a token is not a search.
  if (!["tab", "q", "saved", "range"].some((k) => p.has(k))) return null;
  const range = p.get("range") ?? "24h";
  const state: SearchUrlState = {
    tab: p.get("tab") === "sql" ? "sql" : "simple",
    range: (RANGES.has(range) ? range : "24h") as TimeRangeId,
  };
  const saved = p.get("saved");
  if (saved && ID.test(saved)) {
    state.saved = saved;
    const params: Record<string, string> = {};
    for (const [k, v] of p.entries()) if (k.startsWith("p.")) params[k.slice(2)] = v;
    state.params = params;
    return state;
  }
  const q = p.get("q");
  if (q !== null) state.q = q.slice(0, MAX_Q);
  return state;
}

/** Record a run. The first run of a page replaces the entry it opened on; later runs add
 * one, unless nothing changed. No navigation event: the page already shows this state. */
export function recordSearch(state: SearchUrlState, replace: boolean): void {
  const url = searchUrl(state);
  if (window.location.pathname + window.location.search + window.location.hash === url) return;
  if (replace) window.history.replaceState(null, "", url);
  else window.history.pushState(null, "", url);
  rememberRecent(state, url);
}

// --- Back and Forward: the page is rebuilt from the address it lands on --------------------

let version = 0;
const listeners = new Set<() => void>();

function bump() {
  version += 1;
  listeners.forEach((l) => l());
}

if (typeof window !== "undefined") {
  window.addEventListener("popstate", () => {
    if (window.location.pathname === "/search") bump();
  });
}

export function subscribeSearchNav(callback: () => void): () => void {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

export function searchNavVersion(): number {
  return version;
}

/** Go to a search address (New search, a recent search) as a new history entry. */
export function goToSearch(url: string): void {
  window.history.pushState(null, "", url);
  window.dispatchEvent(new Event("app:navigate"));
  bump();
}

// --- Recent searches: the last 10 runs, in this browser only -------------------------------

export interface RecentSearch {
  label: string;
  url: string;
  at: string;
}

const RECENT_KEY = "search-recent";
const RECENT_MAX = 10;

function label(state: SearchUrlState): string {
  if (state.saved) return `Saved search ${state.saved}`;
  const q = (state.q ?? "").replace(/\s+/g, " ").trim();
  if (!q) return state.tab === "sql" ? "SQL (too long to keep)" : "All events";
  return q.length > 90 ? `${q.slice(0, 89)}…` : q;
}

export function recentSearches(): RecentSearch[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    const list = raw ? (JSON.parse(raw) as RecentSearch[]) : [];
    if (!Array.isArray(list)) return [];
    // Entries kept before the fragment change used `/search?`; never send those again.
    return list
      .slice(0, RECENT_MAX)
      .map((r) => ({ ...r, url: r.url.replace(/^\/search\?/, "/search#") }));
  } catch {
    return []; // storage blocked or unreadable
  }
}

/** Forget the recent searches kept in this browser. */
export function clearRecent(): void {
  try {
    window.localStorage.removeItem(RECENT_KEY);
  } catch {
    // storage blocked: nothing kept to clear
  }
}

function rememberRecent(state: SearchUrlState, url: string): void {
  try {
    const next = [
      { label: label(state), url, at: new Date().toISOString() },
      ...recentSearches().filter((r) => r.url !== url),
    ].slice(0, RECENT_MAX);
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // storage blocked: recent searches last for this visit only
  }
}
