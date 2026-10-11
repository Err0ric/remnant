import { useSyncExternalStore } from "react";

/** Pages that exist today. Unknown paths, and the root, open the Overview (ADR-0008). */
export type PageId =
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
  | "audit";

const PATHS: Record<PageId, string> = {
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

export function navigate(page: PageId) {
  if (window.location.pathname === PATHS[page]) return;
  window.history.pushState(null, "", PATHS[page]);
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
