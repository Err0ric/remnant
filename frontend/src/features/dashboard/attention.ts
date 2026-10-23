import { useQuery } from "@tanstack/react-query";
import { api, type Dashboard, type Schedule } from "@/lib/api";

export interface Attention {
  /** Flagged panels across the viewer's dashboards, not yet acknowledged, one per schedule. */
  items: Schedule[];
  loading: boolean;
}

/** The same rule as the Dashboard's Needs attention strip (ADR-0034 row 3), across every
 * dashboard the viewer sees, for Health's tile (F55). */
export function flagged(dashboards: Dashboard[], schedules: Schedule[]): Schedule[] {
  const byId = new Map(schedules.map((s) => [s.schedule_id, s]));
  const out = new Map<string, Schedule>();
  for (const d of dashboards)
    for (const p of d.panels) {
      const s = byId.get(p.schedule_id);
      const last = s?.recent[0];
      if (s && last && last.flagged && !last.restricted && d.acks[s.schedule_id] !== last.run_id)
        out.set(s.schedule_id, s);
    }
  return [...out.values()].sort((a, b) =>
    (b.recent[0]?.started_at ?? "").localeCompare(a.recent[0]?.started_at ?? ""),
  );
}

export function useAttention(): Attention {
  const dashboards = useQuery({ queryKey: ["dashboards"], queryFn: api.dashboards });
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: api.schedules });
  return {
    items: flagged(dashboards.data ?? [], schedules.data ?? []),
    loading: dashboards.isLoading || schedules.isLoading,
  };
}
