import { Skeleton } from "@/components/Skeleton";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { InlineError } from "@/components/InlineError";
import { When } from "@/components/When";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { navigate } from "@/lib/route";
import { Card } from "@/components/Card";

/** Alerts about the person (ADR-0038 row 27): the open ones first on the Record page
 * (ADR-0052), the closed ones behind "Show closed". Without View people in AI usage the
 * server leaves AI Watch items out (D242, amended 2026-11-11). */
export function PersonAlerts({ person }: { person: string }) {
  const q = useQuery({
    queryKey: ["person-alerts", person],
    queryFn: () => api.personAlerts(person),
  });
  const [closedToo, setClosedToo] = useState(false);
  const all = q.data?.items ?? [];
  const closed = all.filter((i) => i.state !== "open").length;
  const items = closedToo ? all : all.filter((i) => i.state === "open");
  return (
    <Card
      title="Open alerts"
      note="Alerts that name this person, newest first"
      action={
        closed ? (
          <button
            type="button"
            aria-pressed={closedToo}
            onClick={() => setClosedToo((v) => !v)}
            className="text-sm text-accent-text hover:underline"
          >
            {closedToo ? "Hide closed" : `Show ${closed.toLocaleString()} closed`}
          </button>
        ) : null
      }
    >
      {q.isLoading ? (
        <Skeleton label="this list" rows={3} className="rounded-none border-0" />
      ) : q.isError ? (
        <InlineError
          what="alerts"
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
        />
      ) : !items.length ? (
        <p className="px-3 py-4 text-sm text-text-secondary">
          {closed ? "No open alerts name this person." : "No alerts name this person."}
        </p>
      ) : (
        <ul className="flex flex-col">
          {items.map((i) => (
            <li
              key={i.item_id}
              className="grid grid-cols-[8rem_minmax(0,1fr)_auto] items-baseline gap-x-3 border-b border-border px-3 py-1.5 text-sm last:border-0"
            >
              <span className="whitespace-nowrap text-text-muted">
                <When iso={i.created_at} />
              </span>
              <button
                type="button"
                onClick={() => navigate("alerts", `item=${i.item_id}`)}
                className={cn(
                  "min-w-0 truncate text-left hover:underline",
                  i.state === "open" ? "text-text" : "text-text-secondary",
                )}
              >
                {i.title}
              </button>
              <span className="text-text-secondary">
                {i.state === "open" ? "Open" : (i.close_reason_label ?? "Closed")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
