import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api } from "@/lib/api";
import { navigate } from "@/lib/route";
import { SchedulePanel } from "./SchedulePanel";

/** A panel per schedule you own or that is shared with you (SPEC 5.5). */
export function DashboardPage() {
  const schedules = useQuery({
    queryKey: ["schedules"],
    queryFn: api.schedules,
    refetchInterval: 60_000,
  });
  const list = schedules.data ?? [];
  const flagged = list.filter((s) => s.recent[0]?.flagged && !s.recent[0].restricted).length;
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        crumbs={["Home", "General", "Dashboard"]}
        title="Dashboard"
        meta={`${list.length} ${list.length === 1 ? "panel" : "panels"}${flagged ? ` · ${flagged} flagged` : ""}`}
      />
      <div className="flex flex-col gap-3 px-5 py-3">
        {schedules.error ? (
          <p role="alert" className="text-sm text-danger">
            {schedules.error instanceof ApiError ? schedules.error.message : "Could not load"}
          </p>
        ) : null}
        {list.length === 0 && schedules.isSuccess ? (
          <div className="rounded-card border border-border bg-surface px-3 py-8 text-center text-sm">
            <p className="font-semibold">No panels yet</p>
            <p className="text-text-secondary">
              Each scheduled saved search or rule gets a panel here.
            </p>
            <button
              type="button"
              className="mt-2 rounded px-2 py-1 text-accent-text hover:bg-surface-head"
              onClick={() => navigate("schedules")}
            >
              Go to Schedules
            </button>
          </div>
        ) : null}
        <div className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,360px),1fr))] gap-3">
          {list.map((s) => (
            <SchedulePanel key={s.schedule_id} schedule={s} />
          ))}
        </div>
      </div>
    </div>
  );
}
