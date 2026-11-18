import { useSyncExternalStore } from "react";

/** Pages that exist today. The root opens Home, which always picks the Dashboard. Old
 * addresses open their new page (`OLD_ADDRESSES`); any other address is `notfound`, which
 * shows "Page not found" in the app shell and keeps the address as typed. */
export type PageId =
  | "home"
  | "logs"
  | "ask"
  | "sources"
  | "templates"
  | "users"
  | "providers"
  | "account"
  | "me"
  | "saved"
  | "library"
  | "rules"
  | "schedules"
  | "dashboard"
  | "alerts"
  | "handling"
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
  | "system"
  | "aisettings"
  | "agents"
  | "m365"
  | "plugins"
  | "sso"
  | "notfound";

export const PATHS: Readonly<Record<PageId, string>> = {
  home: "/",
  logs: "/investigate/logs",
  ask: "/ask-ai",
  sources: "/sources",
  templates: "/templates",
  users: "/users",
  providers: "/providers",
  me: "/me",
  saved: "/investigate/saved",
  // Logs > Library (owner, 2026-11-17): the query library, which was a panel on Logs.
  library: "/investigate/library",
  rules: "/alerts/rules",
  schedules: "/alerts/schedules",
  dashboard: "/dashboard",
  alerts: "/alerts",
  // Alerts > Handling (D261): how alerts are handled, as numbers.
  handling: "/alerts/handling",
  targets: "/alert-targets",
  ai: "/ai",
  investigate: "/investigate/people",
  agents: "/agents",
  // Microsoft 365 has no area of its own (ADR-0052 section 3.3): Sign-ins, Mail, and Admin
  // are views of Logs. The page keeps its id.
  m365: "/investigate/views",
  plugins: "/plugins",
  sso: "/sso",
  identities: "/identities",
  setup: "/setup",
  health: "/health",
  // Settings > System (ADR-0052 section 3.3): Backups, Page rollups, and Speed, which were
  // Health tabs. Administrators only (owner, 2026-11-13).
  system: "/system",
  // Settings > AI: the AI watch, the MCP server rules, and the service catalog, which were
  // on AI usage > Review (ADR-0052 section 3.3; owner, 2026-11-13).
  aisettings: "/ai-settings",
  mcp: "/mcp-server",
  enrichment: "/enrichment",
  audit: "/audit",
  about: "/about",
  account: "/account", // invite and reset links land here; works signed out
  notfound: "", // never an address of its own: the page for an address nothing claims
};
const CHANGE = "app:navigate";

/** Tabs a page shows as `/<page path>/<tab>` (ADR-0038 row 3). The first is the default
 * and has no segment of its own. */
export const PAGE_TABS: Partial<Record<PageId, readonly string[]>> = {
  ai: ["services", "people", "inventory"],
  m365: ["sign-ins", "mail", "admin"],
  agents: ["sessions", "mcp", "accounts"],
  health: ["sources", "collectors", "delivery"],
  audit: ["activity", "ai", "integrity"],
};

/** Where an old address opens now. */
export interface OldAddress {
  page: PageId;
  /** The tab of that page ("" or left out: its first). */
  tab?: string;
  /** Filter state the new address starts its fragment with (`type=devices`). */
  add?: string;
}

/** Every address the app served before and no longer serves, and where it opens now
 * (ADR-0052 section 3.4), so links already sent (alert messages, bookmarks, guides) open
 * the right page. A key is a path, or a path with the bare `#word` that named a tab before
 * tabs had paths. The new address replaces the old one (Back does not return to it) and
 * keeps the query string and the fragment, except a `#word` its key names. Current tab
 * names in a `#word` (`/health#delivery`) need no entry: they become the tab's path. */
export const OLD_ADDRESSES: Readonly<Record<string, OldAddress>> = {
  // Addresses people type: an area's first word, and Settings itself (owner, 2026-11-16).
  "/investigate": { page: "investigate" },
  "/investigate/ask": { page: "ask" },
  "/settings": { page: "sources" }, // where the rail's Settings opens for every role
  // The former Overview is Health (ADR-0034 row 11).
  "/overview": { page: "health" },
  // Before ADR-0038 and D206: Logs and Ask AI before their names settled.
  "/search": { page: "logs" },
  "/investigate/search": { page: "logs" },
  "/ask": { page: "ask" },
  "/saved": { page: "saved" },
  "/rules": { page: "rules" },
  "/schedules": { page: "schedules" },
  "/investigations": { page: "investigate" },
  // Alerts: Open, Closed, and Muted were tabs and are the Queue's State filter (3.3).
  "/alerts/open": { page: "alerts" },
  "/alerts/closed": { page: "alerts", add: "state=closed" },
  "/alerts/muted": { page: "alerts", add: "state=muted" },
  "/alerts#open": { page: "alerts" },
  "/alerts#closed": { page: "alerts", add: "state=closed" },
  "/alerts#muted": { page: "alerts", add: "state=muted" },
  // AI usage: Review is the Inventory, which picks Unreviewed or All itself (no Status in
  // the address); its settings are Settings > AI watch and catalog; two tabs went to Agents.
  "/ai/settings": { page: "ai", tab: "inventory" },
  "/ai#settings": { page: "ai", tab: "inventory" },
  "/ai/watch": { page: "aisettings" }, // never a page, but reads like one (owner, 2026-10-31)
  "/ai#agents": { page: "agents" },
  "/ai#mcp": { page: "agents", tab: "mcp" },
  // Agents: the Overview is a strip on Sessions; Tools are rows of MCP servers.
  "/agents/overview": { page: "agents" },
  "/agents#overview": { page: "agents" },
  "/agents/tools": { page: "agents", tab: "mcp" },
  "/agents#tools": { page: "agents", tab: "mcp" },
  // Health's old tabs, by path and by hash: Enrichment feeds is a Type of Sources, Endpoint
  // agents and Watched devices are Collectors, Delivery has its own name, and Backups, Page
  // rollups, and Speed are Settings > System.
  ...healthTab("enrichment", { page: "health", add: "type=enrichment" }),
  ...healthTab("agents", { page: "health", tab: "collectors" }),
  ...healthTab("devices", { page: "health", tab: "collectors", add: "type=devices" }),
  ...healthTab("alerts", { page: "health", tab: "delivery" }),
  ...healthTab("backups", { page: "system" }),
  ...healthTab("rollups", { page: "system", add: "type=rollups" }),
  ...healthTab("speed", { page: "system", add: "type=speed" }),
  // Integrity alerts linked here before the check moved to Settings > Audit log.
  "/health#integrity": { page: "audit", tab: "integrity" },
  // Microsoft 365 (3.3, D249): Sign-ins, Mail, and Admin are Logs views, the Overview is
  // the top of the Sign-ins view, and Apps is a Type of the AI usage Inventory.
  ...m365Tab("overview", { page: "m365" }),
  ...m365Tab("sign-ins", { page: "m365" }),
  ...m365Tab("mail", { page: "m365", tab: "mail" }),
  ...m365Tab("admin", { page: "m365", tab: "admin" }),
  ...m365Tab("apps", { page: "ai", tab: "inventory", add: "type=m365_app" }),
  "/m365": { page: "m365" },
};
function healthTab(word: string, to: OldAddress): Record<string, OldAddress> {
  return { [`/health/${word}`]: to, [`/health#${word}`]: to };
}
function m365Tab(word: string, to: OldAddress): Record<string, OldAddress> {
  return { [`/m365/${word}`]: to, [`/m365#${word}`]: to };
}

/** The old address a path and fragment are, and the fragment the new one keeps. Own keys
 * only: the words come from the address, and `constructor` is not an address. */
function oldAddress(path: string, hash: string): { to: OldAddress; rest: string } | null {
  const word = /^[\w-]+$/.test(hash) ? `${path}#${hash}` : "";
  if (word && Object.hasOwn(OLD_ADDRESSES, word)) {
    const to = OLD_ADDRESSES[word];
    if (to) return { to, rest: "" };
  }
  const to = Object.hasOwn(OLD_ADDRESSES, path) ? OLD_ADDRESSES[path] : undefined;
  return to ? { to, rest: hash } : null;
}

/** Health's Status filter (D255): All, Problems, Paused, Healthy; anything else is All. */
export const HEALTH_STATUS = ["all", "problems", "paused", "healthy", "shared"] as const;
export type HealthStatus = (typeof HEALTH_STATUS)[number];
export function healthStatus(frag: URLSearchParams): HealthStatus {
  const v = frag.get("status") ?? "";
  return (HEALTH_STATUS as readonly string[]).includes(v) ? (v as HealthStatus) : "all";
}

interface Place {
  page: PageId;
  tab: string;
}

function parse(pathname: string, hash: string): Place {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  // Before the exact match: `/health#speed` is the Health path with an old tab's hash.
  const old = oldAddress(path, hash);
  if (old) return { page: old.to.page, tab: old.to.tab ?? "" };
  const exact = (Object.keys(PATHS) as PageId[]).find((id) => PATHS[id] && path === PATHS[id]);
  if (exact) {
    // `/health#delivery`, from before tabs had paths.
    const first = PAGE_TABS[exact]?.[0];
    return { page: exact, tab: PAGE_TABS[exact]?.includes(hash) && hash !== first ? hash : "" };
  }
  for (const id of Object.keys(PAGE_TABS) as PageId[]) {
    const base = PATHS[id];
    if (path.startsWith(`${base}/`)) {
      const tab = path.slice(base.length + 1);
      if (PAGE_TABS[id]?.includes(tab)) return { page: id, tab };
    }
  }
  return { page: "notfound", tab: "" };
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

/** The canonical address for the current one: old addresses become their new page, and
 * `#tab` hashes become `/<page>/<tab>`; the query string and other fragment state
 * (`#item=...`) are kept. Returns null when unchanged, and for an address nothing claims,
 * which stays as typed so the person can see and fix it. */
export function canonical(): string | null {
  const hash = window.location.hash.replace(/^#/, "");
  const path = window.location.pathname.replace(/(.)\/+$/, "$1");
  const search = window.location.search;
  const old = oldAddress(path, hash);
  if (old) {
    const fragment = [old.to.add ?? "", old.rest].filter(Boolean).join("&");
    return pathFor(old.to.page, old.to.tab) + search + (fragment ? `#${fragment}` : "");
  }
  const { page, tab } = here();
  if (page === "notfound") return null;
  const keep = hash && !PAGE_TABS[page]?.includes(hash) ? `#${hash}` : "";
  const target = pathFor(page, tab) + search + keep;
  return target === window.location.pathname + search + window.location.hash ? null : target;
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

/** Sets the fragment of the address the person is on, keeping its path (so its tab) and
 * query string: the state a page keeps in the URL (filters, the open row). `replace` adds no
 * step to Back. */
export function setFragment(state: string, replace = false) {
  const to = window.location.pathname + window.location.search + (state ? `#${state}` : "");
  if (to === window.location.pathname + window.location.search + window.location.hash) return;
  if (replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
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

/** The path of the address as typed (percent escapes read back), for the page that says
 * nothing is there. */
export function usePathname(): string {
  return useSyncExternalStore(subscribe, () => {
    try {
      return decodeURI(window.location.pathname);
    } catch {
      return window.location.pathname; // a broken escape: shown as it came
    }
  });
}

function currentHash(): string {
  return window.location.hash.replace(/^#/, "");
}

/** A fragment as named values: `#state=closed&item=a1`. A bare word (`#review`) is a name
 * with no value. */
export function fragmentValues(section: string): URLSearchParams {
  return new URLSearchParams(section);
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
