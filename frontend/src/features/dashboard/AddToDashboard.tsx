import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, type QueryResult, type SavedSearch } from "@/lib/api";
import { navigate } from "@/lib/route";
import { seedSchedule } from "@/lib/scheduleSeed";
import { currentDashboard } from "./choice";
import { barShape } from "./panelShape";

/** Defaults for a panel made in one step (docs/ux-next-click.md part c). */
export const PANEL_DEFAULTS = {
  cron: "hourly",
  lookback_minutes: 1440,
  shared: false,
} as const;

/** Create the schedule behind a Dashboard panel and run it once so the panel fills now.
 * A result shaped like a label and a count starts as bars. */
export async function addToDashboard(
  search: SavedSearch,
  name: string,
  result?: QueryResult | null,
): Promise<void> {
  const board = currentDashboard();
  const schedule = await api.createSchedule({
    kind: "search",
    target_id: search.id,
    name: name.trim() || search.name,
    ...PANEL_DEFAULTS,
    // The dashboard last opened in this browser; the server falls back to the first one.
    ...(board ? { dashboard_id: board } : {}),
    ...(result && barShape(result.columns, result.rows.slice(0, 10))
      ? { panel_view: "bars" as const }
      : {}),
  });
  try {
    await api.runSchedule(schedule.schedule_id);
  } catch {
    // The panel shows the failure or waits for the hourly run; the schedule exists either way.
  }
}

interface AddToDashboardPanelProps {
  search: SavedSearch;
  result?: QueryResult | null;
  onClose: () => void;
}

/** One step from a result to a Dashboard panel: name, the defaults on one line, Add. */
export function AddToDashboardPanel({ search, result = null, onClose }: AddToDashboardPanelProps) {
  const client = useQueryClient();
  const [name, setName] = useState(search.name);
  const bars = Boolean(result && barShape(result.columns, result.rows.slice(0, 10)));
  const add = useMutation({
    mutationFn: () => addToDashboard(search, name, result),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["schedules"] });
      onClose();
      navigate("dashboard");
    },
  });
  return (
    <form
      aria-label="Add to dashboard"
      className="flex flex-col gap-2 rounded-card border border-border bg-surface p-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        add.mutate();
      }}
    >
      <label className="flex max-w-md flex-col gap-1">
        <span className="text-text-secondary">Panel name</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="h-8 rounded border border-border-strong bg-inset px-2"
        />
      </label>
      <p className="text-text-secondary">
        Hourly, last 24 hours, {bars ? "bars" : "table"}, a third wide, private.{" "}
        <button
          type="button"
          className="text-accent-text hover:underline"
          onClick={() => {
            seedSchedule({ kind: "search", targetId: search.id });
            navigate("schedules");
          }}
        >
          Change
        </button>
      </p>
      {add.error ? (
        <p role="alert" className="text-danger">
          {add.error instanceof ApiError ? add.error.message : "That did not work"}
        </p>
      ) : null}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={add.isPending}
          className="h-8 rounded bg-accent px-3 font-semibold text-white disabled:opacity-40"
        >
          {add.isPending ? "Adding…" : "Add to dashboard"}
        </button>
        <button type="button" onClick={onClose} className="h-8 rounded px-3 hover:bg-surface-head">
          Cancel
        </button>
      </div>
    </form>
  );
}
