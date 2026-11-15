import { useEffect, useSyncExternalStore } from "react";
import type { Entity } from "@/lib/entity";

/** The rail's Recent (D258): the last entities the viewer opened (people, hosts, and
 * addresses), newest first, kept in this browser per signed-in user and never sent to the
 * server; cleared at sign-out. Without View people in AI usage (D242) people are neither
 * kept nor shown, and any kept before the permission was taken away are removed. */
export type RecentKind = "user" | "host" | "ip";
export interface RecentEntity {
  kind: RecentKind;
  value: string;
}

export const RECENT_MAX = 5;
const PREFIX = "app.recent.";
const KINDS: readonly string[] = ["user", "host", "ip"];

function key(user: string): string {
  return `${PREFIX}${user || "local"}`;
}

function valid(v: unknown): v is RecentEntity {
  if (typeof v !== "object" || v === null) return false;
  const r = v as Record<string, unknown>;
  return typeof r.kind === "string" && KINDS.includes(r.kind) && typeof r.value === "string";
}

function read(user: string): RecentEntity[] {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(key(user)) ?? "[]");
    return Array.isArray(value) ? value.filter(valid).slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

// A change made here redraws the rail at once; the cached list keeps snapshots stable.
const listeners = new Set<() => void>();
const cache = new Map<string, { raw: string; list: RecentEntity[] }>();

function snapshot(user: string): RecentEntity[] {
  let raw = "[]";
  try {
    raw = window.localStorage.getItem(key(user)) ?? "[]";
  } catch {
    // Storage blocked: Recent stays empty.
  }
  const hit = cache.get(user);
  if (hit && hit.raw === raw) return hit.list;
  const list = read(user);
  cache.set(user, { raw, list });
  return list;
}

function write(user: string, list: RecentEntity[]): void {
  try {
    window.localStorage.setItem(key(user), JSON.stringify(list));
  } catch {
    return; // Storage blocked: nothing is kept.
  }
  listeners.forEach((l) => l());
}

/** Keeps an opened entity at the top (once), at most RECENT_MAX. A service is not kept;
 * without the permission no person is kept, including any kept before. */
export function rememberEntity(user: string, e: Entity, canViewPeople: boolean): void {
  if (!KINDS.includes(e.kind) || (e.kind === "user" && !canViewPeople)) return;
  const item: RecentEntity = { kind: e.kind as RecentKind, value: e.value };
  const rest = read(user).filter(
    (r) => (r.kind !== item.kind || r.value !== item.value) && (canViewPeople || r.kind !== "user"),
  );
  write(user, [item, ...rest].slice(0, RECENT_MAX));
}

/** Removes every person from a user's Recent: the viewer may no longer see people. */
function forgetPeople(user: string): void {
  const list = read(user);
  if (list.some((r) => r.kind === "user"))
    write(
      user,
      list.filter((r) => r.kind !== "user"),
    );
}

/** At sign-out, or when the sign-in page shows (a session that ended): every Recent kept in
 * this browser is removed, so the next person at it cannot read it. */
export function forgetAllRecent(): void {
  try {
    const keys = Array.from({ length: window.localStorage.length }, (_, i) =>
      window.localStorage.key(i),
    );
    for (const k of keys) if (k?.startsWith(PREFIX)) window.localStorage.removeItem(k);
  } catch {
    return; // Storage blocked: nothing was kept.
  }
  cache.clear();
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** What Recent shows: people only for a viewer who may see them, even if kept before. */
export function useRecentEntities(user: string, canViewPeople: boolean): RecentEntity[] {
  const list = useSyncExternalStore(subscribe, () => snapshot(user));
  const holdsPeople = list.some((e) => e.kind === "user");
  useEffect(() => {
    if (!canViewPeople && holdsPeople) forgetPeople(user);
  }, [user, canViewPeople, holdsPeople]);
  return canViewPeople ? list : list.filter((e) => e.kind !== "user");
}
