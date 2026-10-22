import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";

interface RetentionEditorProps {
  sourceId: string;
  value: number;
  canManage: boolean;
}

const PRESETS = [30, 90, 180, 365];

/** How many days of a source's events are kept (install finding F44). The nightly
 * retention job applies a change; audited source.retention_change. */
export function RetentionEditor({ sourceId, value, canManage }: RetentionEditorProps) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [days, setDays] = useState(String(value));
  const n = Number(days);
  const valid = Number.isInteger(n) && n >= 1 && n <= 3650;
  const save = useMutation({
    mutationFn: () => api.setSourceRetention(sourceId, n),
    onSuccess: () => {
      setOpen(false);
      void client.invalidateQueries({ queryKey: ["source-list"] });
      void client.invalidateQueries({ queryKey: ["sources"] });
    },
  });
  if (!open) {
    return (
      <span className="flex items-center gap-2">
        <span className="tabular-nums">{value} days</span>
        {canManage ? (
          <button
            type="button"
            aria-label={`Change retention of ${sourceId}`}
            onClick={() => {
              setDays(String(value));
              setOpen(true);
            }}
            className="text-sm text-accent-text hover:underline"
          >
            Change
          </button>
        ) : null}
      </span>
    );
  }
  return (
    <form
      aria-label={`Retention of ${sourceId}`}
      className="flex max-w-[20rem] flex-col gap-1.5 whitespace-normal text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) save.mutate();
      }}
    >
      <label className="flex flex-col gap-1">
        <span className="text-text-secondary">Keep events for (days)</span>
        <input
          type="number"
          min={1}
          max={3650}
          value={days}
          onChange={(e) => setDays(e.target.value)}
          className="h-8 w-28 rounded border border-border-strong bg-inset px-2 font-mono tabular-nums"
        />
      </label>
      <span className="flex flex-wrap gap-1.5">
        {PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setDays(String(p))}
            className="h-6 rounded border border-border px-2 text-xs tabular-nums hover:bg-surface-head"
          >
            {p}
          </button>
        ))}
      </span>
      <span className={valid && n < value ? "text-warn" : "text-text-muted"}>
        {valid && n < value
          ? `Days older than ${n} are deleted on the next nightly run.`
          : "Applied by the nightly retention job. Days already deleted do not come back."}
      </span>
      {save.error ? (
        <span role="alert" className="text-danger">
          {save.error instanceof ApiError ? save.error.message : "That did not work"}
        </span>
      ) : null}
      <span className="flex gap-2">
        <button
          type="submit"
          disabled={!valid || n === value || save.isPending}
          className="h-7 rounded bg-accent px-2.5 font-semibold text-white disabled:opacity-40"
        >
          Save
        </button>
        <button type="button" onClick={() => setOpen(false)} className="h-7 rounded px-2.5">
          Cancel
        </button>
      </span>
    </form>
  );
}
