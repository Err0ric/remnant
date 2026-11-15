import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "@/lib/api";

/** The viewer's pins (D259): kept on the server, at most MAX_PINS, oldest first. */
export const MAX_PINS = 5;
export const PINS_KEY = ["pins"] as const;

export function usePins() {
  return useQuery({ queryKey: PINS_KEY, queryFn: api.pins, staleTime: 60_000 });
}

/** Pins name their targets, so any change to saved searches or dashboards (a delete, a
 * rename, a share taken away) refreshes them at once: whatever invalidates ["searches"]
 * or ["dashboards"], anywhere in the app, invalidates the pins too. Used once, by the rail. */
export function usePinsFollowTargets(): void {
  const client = useQueryClient();
  useEffect(
    () =>
      client.getQueryCache().subscribe((e) => {
        const head = e.query.queryKey[0];
        if (
          e.type === "updated" &&
          e.action.type === "invalidate" &&
          (head === "searches" || head === "dashboards")
        )
          void client.invalidateQueries({ queryKey: PINS_KEY });
      }),
    [client],
  );
}

/** The saved search a pin opens (`open=<id>` on Saved searches) and the dashboard
 * (`board=<id>` on the Dashboard): the target in the address, so a new tab opens it too. */
export function targetIn(section: string, name: "open" | "board"): string | null {
  const m = new RegExp(`^${name}=([^&]+)`).exec(section);
  if (!m?.[1]) return null;
  try {
    return decodeURIComponent(m[1]);
  } catch {
    return null;
  }
}

export function targetSection(name: "open" | "board", id: string): string {
  return `${name}=${encodeURIComponent(id)}`;
}
