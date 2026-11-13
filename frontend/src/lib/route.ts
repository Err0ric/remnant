import { useSyncExternalStore } from "react";

/** Pages that exist today. The root opens Home, which picks the Dashboard when the viewer
 * has a panel and Health otherwise (ADR-0031, ADR-0034 row 11). `/overview` and unknown
 * paths open Health > Sources, where the former Overview's numbers now live. */
export type PageId =
  | "home"
  | "overview"
  | "logs"
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
  | "system"
  | "aisettings"
  | "agents"
  | "m365"
  | "plugins"
  | "sso";

const PATHS: Record<PageId, string> = {
  home: "/",
  overview: "/overview",
  logs: "/investigate/logs",
  ask: "/ask-ai",
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
};
const CHANGE = "app:navigate";

/** Tabs a page shows as `/<page path>/<tab>` (ADR-0038 row 3). The first is the default
 * and has no segment of its own. */
export const PAGE_TABS: Partial<Record<PageId, readonly string[]>> = {
  ai: ["services", "people", "inventory"],
  m365: ["sign-ins", "mail", "admin"],
  // Overview and Tools are gone (ADR-0052 section 3.3): the numbers are a strip on
  // Sessions and the tools are rows of MCP servers. Their old addresses still open.
  agents: ["sessions", "mcp", "accounts"],
  health: ["sources", "collectors", "delivery"],
  audit: ["activity", "ai", "integrity"],
};

/** Paths before ADR-0038, kept so links already sent (alert messages, bookmarks) open the
 * same place. A legacy path's `#tab` becomes the tab segment. */
const LEGACY: Record<string, PageId> = {
  "/search": "logs",
  // Logs and Ask AI before their names settled (D206); search state in the fragment is kept.
  "/investigate/search": "logs",
  "/ask": "ask",
  "/saved": "saved",
  "/rules": "rules",
  "/schedules": "schedules",
  "/investigations": "investigate",
};
/** Alerts: Open, Closed, and Muted were tabs (`/alerts/closed`) and are now the State filter
 * of the Queue, kept in the fragment (`/alerts#state=closed`; ADR-0052 sections 3.3, 3.4). */
const ALERT_STATES = ["open", "closed", "muted"] as const;
function oldAlertState(path: string): string | null {
  const state = path.startsWith(`${PATHS.alerts}/`) ? path.slice(PATHS.alerts.length + 1) : "";
  return (ALERT_STATES as readonly string[]).includes(state) ? state : null;
}

/** The Microsoft 365 area's old addresses (`/m365/mail`, and `/m365#mail` from before tabs
 * had paths), each where its content now is (ADR-0052 sections 3.3 and 3.4): Sign-ins,
 * Mail, and Admin are Logs views, the Overview is the top of the Sign-ins view, and Apps is
 * a Type of the AI usage Inventory. */
const M365_OLD = "/m365";
function oldM365(path: string, hash: string): Place | null {
  if (path !== M365_OLD && !path.startsWith(`${M365_OLD}/`)) return null;
  const tab = path === M365_OLD ? hash : path.slice(M365_OLD.length + 1);
  if (tab === "mail" || tab === "admin") return { page: "m365", tab };
  if (tab === "apps") return { page: "ai", tab: "inventory" };
  // Sign-ins, and the Overview, whose charts and lists are at the top of that view.
  return { page: "m365", tab: "" };
}

/** Health's old tabs (`/health/agents`, and `/health#agents` from before tabs had paths),
 * each where it is now (ADR-0052 sections 3.3 and 3.4): Enrichment feeds is a Type of
 * Sources, Endpoint agents and Watched devices are Types of Collectors, Delivery has its own
 * name, and Backups, Page rollups, and Speed are Settings > System. `type` is the Type
 * filter the new address carries in its fragment. */
const HEALTH_OLD: Record<string, { place: Place; type?: string }> = {
  enrichment: { place: { page: "health", tab: "" }, type: "enrichment" },
  agents: { place: { page: "health", tab: "collectors" } },
  devices: { place: { page: "health", tab: "collectors" }, type: "devices" },
  alerts: { place: { page: "health", tab: "delivery" } },
  backups: { place: { page: "system", tab: "" } },
  rollups: { place: { page: "system", tab: "" }, type: "rollups" },
  speed: { place: { page: "system", tab: "" }, type: "speed" },
};
function oldHealth(path: string, hash: string): { place: Place; type?: string } | null {
  const base = "/health";
  if (path !== base && !path.startsWith(`${base}/`)) return null;
  // Own names only: the word comes from the address, and `constructor` is not a tab.
  const old = path === base ? hash : path.slice(base.length + 1);
  return Object.hasOwn(HEALTH_OLD, old) ? (HEALTH_OLD[old] ?? null) : null;
}

/** Tabs that moved from AI usage to the Agents area, by their old hash. */
const AI_TO_AGENTS: Record<string, string> = { agents: "sessions", mcp: "mcp" };
/** The Agents tab an old AI usage hash stood for, or "" (own names only: the word comes
 * from the address). */
function movedToAgents(hash: string): string {
  return Object.hasOwn(AI_TO_AGENTS, hash) ? (AI_TO_AGENTS[hash] ?? "") : "";
}

interface Place {
  page: PageId;
  tab: string;
}

function parse(pathname: string, hash: string): Place {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  const exact = (Object.keys(PATHS) as PageId[]).find((id) => path === PATHS[id]);
  const legacyHashTab = (page: PageId) =>
    PAGE_TABS[page]?.includes(hash) && hash !== PAGE_TABS[page]?.[0] ? hash : "";
  // Before the exact match: `/health#speed` is the Health path with an old tab's hash.
  const health = oldHealth(path, hash);
  if (health) return health.place;
  if (exact) {
    if (exact === "ai" && hash === "settings") return { page: "ai", tab: "inventory" };
    if (exact === "ai" && movedToAgents(hash)) return { page: "agents", tab: movedToAgents(hash) };
    // `/agents#tools` and `/agents#overview`, from before tabs had paths.
    if (exact === "agents" && hash === "tools") return { page: "agents", tab: "mcp" };
    return { page: exact, tab: legacyHashTab(exact) };
  }
  if (Object.hasOwn(LEGACY, path) && LEGACY[path]) return { page: LEGACY[path], tab: "" };
  if (path === `${PATHS.agents}/overview`) return { page: "agents", tab: "" };
  if (path === `${PATHS.agents}/tools`) return { page: "agents", tab: "mcp" };
  const old = oldM365(path, hash);
  if (old) return old;
  if (oldAlertState(path)) return { page: "alerts", tab: "" };
  // AI Watch's settings (which services and signals it watches): `/ai/watch` was never a
  // page but reads like one (owner, 2026-10-31).
  if (path === "/ai/watch") return { page: "aisettings", tab: "" };
  // The Review tab is gone: reviewing is the Inventory's Status filter (ADR-0052 3.3).
  if (path === "/ai/settings") return { page: "ai", tab: "inventory" };
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
  const path = window.location.pathname.replace(/(.)\/+$/, "$1");
  // `/alerts/closed`, and `/alerts#closed` from before tabs had paths (PR 274).
  const bare = (ALERT_STATES as readonly string[]).includes(hash) ? hash : null;
  const state = oldAlertState(path) ?? (path === PATHS.alerts ? bare : null);
  if (state) {
    // The old tab becomes the State filter; whatever else the fragment held (`item=<id>`)
    // is kept. Open is the default and needs no word.
    const rest = hash && !(ALERT_STATES as readonly string[]).includes(hash) ? hash : "";
    const parts = [state === "open" ? "" : `state=${state}`, rest].filter(Boolean);
    return PATHS.alerts + window.location.search + (parts.length ? `#${parts.join("&")}` : "");
  }
  // AI usage > Review, by path or by its old hash: the Inventory, which opens on Unreviewed
  // while anything is unreviewed and on All otherwise (a Status in the address would
  // switch that fallback off).
  if (path === "/ai/settings" || (path === PATHS.ai && hash === "settings"))
    return pathFor("ai", "inventory") + window.location.search;
  // An old Health tab: its new place, with the Type it stood for in the fragment.
  const health = oldHealth(path, hash);
  if (health) {
    const to = pathFor(health.place.page, health.place.tab) + window.location.search;
    return health.type ? `${to}#type=${health.type}` : to;
  }
  // Microsoft 365 > Apps is the Inventory with its Type set.
  if (path === `${M365_OLD}/apps` || (path === M365_OLD && hash === "apps"))
    return `${pathFor("ai", "inventory")}${window.location.search}#type=m365_app`;
  const wasM365 = path === M365_OLD && ["sign-ins", "mail", "admin", "overview"].includes(hash);
  const oldAgents = path === PATHS.agents && (hash === "tools" || hash === "overview");
  const keep =
    hash && !PAGE_TABS[page]?.includes(hash) && !movedToAgents(hash) && !oldAgents && !wasM365
      ? `#${hash}`
      : "";
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
