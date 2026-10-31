import { useSyncExternalStore } from "react";

/** Pages that exist today. The root opens Home, which picks the Dashboard when the viewer
 * has a panel and Health otherwise (ADR-0031, ADR-0034 row 11). `/overview` and unknown
 * paths open Health > Sources, where the former Overview's numbers now live. */
export type PageId =
  | "home"
  | "overview"
  | "search"
  | "ask"
  | "sources"
  | "templates"
  | "users"
  | "providers"
  | "account"
  | "me"
  | "saved"
  | "rules"
  | "schedules"
  | "dashboard"
  | "alerts"
  | "targets"
  | "ai"
  | "investigate"
  | "identities"
  | "setup"
  | "health"
  | "mcp"
  | "enrichment"
  | "audit"
  | "about"
  | "agents"
  | "m365"
  | "plugins"
  | "sso";

const PATHS: Record<PageId, string> = {
  home: "/",
  overview: "/overview",
  search: "/investigate/search",
  ask: "/ask",
  sources: "/sources",
  templates: "/templates",
  users: "/users",
  providers: "/providers",
  me: "/me",
  saved: "/investigate/saved",
  rules: "/alerts/rules",
  schedules: "/alerts/schedules",
  dashboard: "/dashboard",
  alerts: "/alerts",
  targets: "/alert-targets",
  ai: "/ai",
  investigate: "/investigate/people",
  agents: "/agents",
  m365: "/m365",
  plugins: "/plugins",
  sso: "/sso",
  identities: "/identities",
  setup: "/setup",
  health: "/health",
  mcp: "/mcp-server",
  enrichment: "/enrichment",
  audit: "/audit",
  about: "/about",
  account: "/account", // invite and reset links land here; works signed out
};
const CHANGE = "app:navigate";

/** Tabs a page shows as `/<page path>/<tab>` (ADR-0038 row 3). The first is the default
 * and has no segment of its own. */
export const PAGE_TABS: Partial<Record<PageId, readonly string[]>> = {
  ai: ["services", "people", "settings"],
  m365: ["overview", "sign-ins", "mail", "apps", "admin"],
  agents: ["overview", "sessions", "tools", "mcp", "accounts"],
  health: ["sources", "enrichment", "agents", "devices", "alerts"],
  alerts: ["open", "closed", "muted"],
  audit: ["activity", "ai", "integrity"],
};

/** Paths before ADR-0038, kept so links already sent (alert messages, bookmarks) open the
 * same place. A legacy path's `#tab` becomes the tab segment. */
const LEGACY: Record<string, PageId> = {
  "/search": "search",
  "/saved": "saved",
  "/rules": "rules",
  "/schedules": "schedules",
  "/investigations": "investigate",
};
/** Tabs that moved from AI usage to the Agents area, by their old hash. */
const AI_TO_AGENTS: Record<string, string> = { agents: "sessions", mcp: "mcp" };

interface Place {
  page: PageId;
  tab: string;
}

function parse(pathname: string, hash: string): Place {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  const exact = (Object.keys(PATHS) as PageId[]).find((id) => path === PATHS[id]);
  const legacyHashTab = (page: PageId) =>
    PAGE_TABS[page]?.includes(hash) && hash !== PAGE_TABS[page]?.[0] ? hash : "";
  if (exact) {
    if (exact === "ai" && AI_TO_AGENTS[hash]) return { page: "agents", tab: AI_TO_AGENTS[hash] };
    // `/agents#session=` was the Sessions tab before Overview came first.
    if (exact === "agents" && hash.startsWith("session="))
      return { page: "agents", tab: "sessions" };
    return { page: exact, tab: legacyHashTab(exact) };
  }
  if (LEGACY[path]) return { page: LEGACY[path], tab: "" };
  for (const id of Object.keys(PAGE_TABS) as PageId[]) {
    const base = PATHS[id];
    if (path.startsWith(`${base}/`)) {
      const tab = path.slice(base.length + 1);
      if (PAGE_TABS[id]?.includes(tab)) return { page: id, tab };
    }
  }
  return { page: "overview", tab: "" };
}

function here(): Place {
  return parse(window.location.pathname, window.location.hash.replace(/^#/, ""));
}

export function pageFromPath(pathname: string): PageId {
  return parse(pathname, "").page;
}

export function pathFor(page: PageId, tab?: string): string {
  const first = PAGE_TABS[page]?.[0];
  return tab && tab !== first ? `${PATHS[page]}/${tab}` : PATHS[page];
}

/** The canonical address for the current one: legacy paths and `#tab` hashes become
 * `/<page>/<tab>`; other hash state (`#item=...`) is kept. Returns null when unchanged. */
export function canonical(): string | null {
  const { page, tab } = here();
  const hash = window.location.hash.replace(/^#/, "");
  const keep = hash && !PAGE_TABS[page]?.includes(hash) && !AI_TO_AGENTS[hash] ? `#${hash}` : "";
  if (page === "overview" && window.location.pathname !== PATHS.overview) return null;
  const target = pathFor(page, tab) + window.location.search + keep;
  return target === window.location.pathname + window.location.search + window.location.hash
    ? null
    : target;
}

function target(page: PageId, section?: string): string {
  if (section && PAGE_TABS[page]?.includes(section)) return pathFor(page, section);
  return PATHS[page] + (section ? `#${section}` : "");
}

/** Replaces the current address with a page, without a new history entry (Home's choice). */
export function redirect(page: PageId, section?: string) {
  window.history.replaceState(null, "", target(page, section));
  window.dispatchEvent(new Event(CHANGE));
}

/** Opens a page. `section` is one of its tabs (`/health/sources`) or other state kept in
 * the URL fragment (`#item=<id>`). */
export function navigate(page: PageId, section?: string) {
  const to = target(page, section);
  if (window.location.pathname + window.location.hash === to) return;
  window.history.pushState(null, "", to);
  window.dispatchEvent(new Event(CHANGE));
}

/** Opens a tab of a page with other state in the fragment: `/health/sources#source=x`. */
export function navigateTab(page: PageId, tab: string, state: string) {
  window.history.pushState(null, "", `${pathFor(page, tab)}#${state}`);
  window.dispatchEvent(new Event(CHANGE));
}

function subscribe(callback: () => void) {
  window.addEventListener("popstate", callback);
  window.addEventListener(CHANGE, callback);
  return () => {
    window.removeEventListener("popstate", callback);
    window.removeEventListener(CHANGE, callback);
  };
}

export function usePage(): PageId {
  return useSyncExternalStore(subscribe, () => here().page);
}

/** The open tab of the current page, "" for its first. */
export function useTab(): string {
  return useSyncExternalStore(subscribe, () => here().tab);
}

function currentHash(): string {
  return window.location.hash.replace(/^#/, "");
}

/** State kept in the URL fragment (`#item=<id>`, `#source=<id>`), or "" when there is none. */
export function useSection(): string {
  return useSyncExternalStore(subscribe, currentHash);
}

/** A page's tab, kept in the path so links reach it and Back works (ADR-0038). Unknown or
 * missing tabs fall back to the first allowed one. */
export function useSectionTab<T extends string>(allowed: readonly T[]): [T, (next: T) => void] {
  const current = useTab();
  const page = usePage();
  const tab = (allowed as readonly string[]).includes(current) ? (current as T) : (allowed[0] as T);
  const set = (next: T) => navigate(page, next);
  return [tab, set];
}
