import { useSyncExternalStore } from "react";

/** Pages that exist today. The root opens Home, which picks the Dashboard when the viewer
 * has a panel and the Overview otherwise (ADR-0031); unknown paths open the Overview. */
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
  | "ai"
  | "investigate"
  | "identities"
  | "setup"
  | "health"
  | "mcp"
  | "enrichment"
  | "audit";

const PATHS: Record<PageId, string> = {
  home: "/",
  overview: "/overview",
  search: "/search",
  ask: "/ask",
  sources: "/sources",
  templates: "/templates",
  users: "/users",
  providers: "/providers",
  me: "/me",
  saved: "/saved",
  rules: "/rules",
  schedules: "/schedules",
  dashboard: "/dashboard",
  alerts: "/alert-targets",
  ai: "/ai",
  investigate: "/investigations",
  identities: "/identities",
  setup: "/setup",
  health: "/health",
  mcp: "/mcp-server",
  enrichment: "/enrichment",
  audit: "/audit",
  account: "/account", // invite and reset links land here; works signed out
};
const CHANGE = "app:navigate";

export function pageFromPath(pathname: string): PageId {
  const match = (Object.keys(PATHS) as PageId[]).find((id) => pathname === PATHS[id]);
  return match ?? "overview";
}

export function pathFor(page: PageId): string {
  return PATHS[page];
}

/** Replaces the current address with a page, without a new history entry (Home's choice). */
export function redirect(page: PageId) {
  window.history.replaceState(null, "", PATHS[page]);
  window.dispatchEvent(new Event(CHANGE));
}

/** Opens a page; `section` picks one of its tabs (kept in the URL as `#section`). */
export function navigate(page: PageId, section?: string) {
  const target = PATHS[page] + (section ? `#${section}` : "");
  if (window.location.pathname + window.location.hash === target) return;
  window.history.pushState(null, "", target);
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
  return useSyncExternalStore(subscribe, () => pageFromPath(window.location.pathname));
}

function currentHash(): string {
  return window.location.hash.replace(/^#/, "");
}

/** The section named in the URL (`/ai#agents`), or "" when there is none. */
export function useSection(): string {
  return useSyncExternalStore(subscribe, currentHash);
}

/** A page's tab, kept in the URL so the left nav can link to it and Back works.
 * Unknown or missing sections fall back to the first allowed tab. */
export function useSectionTab<T extends string>(allowed: readonly T[]): [T, (next: T) => void] {
  const hash = useSection();
  const tab = (allowed as readonly string[]).includes(hash) ? (hash as T) : (allowed[0] as T);
  const set = (next: T) => {
    window.history.replaceState(null, "", `${window.location.pathname}#${next}`);
    window.dispatchEvent(new Event(CHANGE));
  };
  return [tab, set];
}
