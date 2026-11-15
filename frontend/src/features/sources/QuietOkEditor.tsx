import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, QUIET_OK_DAYS, api, type QuietOkDays } from "@/lib/api";

interface QuietOkEditorProps {
  sourceId: string;
  value: QuietOkDays | null;
  canManage: boolean;
  /** The source has a quiet alert on: it is held for these days and fires after them (D262). */
  quietAlert?: boolean;
  /** "No events for 2 d (normal for this source)" while the source is idle, else null. */
  idle: string | null;
}

const days = (n: number) => (n === 1 ? "1 day" : `${n} days`);

/** "Quiet is normal for up to N days" on a push source (D260): silence inside those days is
 * not a problem on Health or the Dashboard. Audited source.quiet_ok_change. */
export function QuietOkEditor({
  sourceId,
  value,
  canManage,
  quietAlert = false,
  idle,
}: QuietOkEditorProps) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<QuietOkDays | null>(value);
  const save = useMutation({
    mutationFn: () => api.setSourceQuietOk(sourceId, choice),
    onSuccess: () => {
      setOpen(false);
      void client.invalidateQueries({ queryKey: ["source-list"] });
      void client.invalidateQueries({ queryKey: ["overview"] });
      void client.invalidateQueries({ queryKey: ["health", "count"] });
    },
  });
  const alertNote = quietAlert ? (
    <span data-quiet-alert-note="" className="text-sm text-text-muted">
      Its quiet alert is held for these days and fires after them.
    </span>
  ) : null;
  const said = idle ? <span className="text-sm text-text-secondary">Idle: {idle}</span> : null;
  if (!open) {
    if (!value && !canManage) return said;
    return (
      <>
        {said}
        <span className="flex flex-wrap items-center gap-x-2 text-sm">
          {value ? (
            <span className="text-text-secondary">Quiet is normal for up to {days(value)}</span>
          ) : null}
          {canManage ? (
            <button
              type="button"
              aria-label={`Quiet is normal for ${sourceId}`}
              onClick={() => {
                setChoice(value);
                setOpen(true);
              }}
              className="whitespace-nowrap text-accent-text hover:underline"
            >
              {value ? "Change" : "Quiet is normal"}
            </button>
          ) : null}
        </span>
        {value ? alertNote : null}
      </>
    );
  }
  return (
    <fieldset className="mt-1 flex max-w-[22rem] flex-col gap-1.5 whitespace-normal text-sm">
      <legend className="sr-only">Quiet is normal for {sourceId}</legend>
      <label className="flex flex-col gap-0.5">
        <span className="text-text-secondary">Quiet is normal for up to</span>
        <select
          value={choice ?? "off"}
          onChange={(e) =>
            setChoice(e.target.value === "off" ? null : (Number(e.target.value) as QuietOkDays))
          }
          className="h-7 w-28 rounded border border-border-control bg-surface px-1"
        >
          <option value="off">Off</option>
          {QUIET_OK_DAYS.map((d) => (
            <option key={d} value={d}>
              {days(d)}
            </option>
          ))}
        </select>
      </label>
      <span className="text-text-muted">
        For a source that sends only while people work. Inside these days no events is not a problem
        on Health or the Dashboard and its quiet alert waits; errors still count. After them it
        reads as quiet and the alert fires.
      </span>
      {alertNote}
      {save.error ? (
        <span role="alert" className="text-danger">
          {save.error instanceof ApiError ? save.error.message : "Could not save"}
        </span>
      ) : null}
      <span className="flex gap-2">
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending || choice === value}
          className="h-7 rounded bg-accent px-3 font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="h-7 rounded border border-border-strong px-3 hover:bg-surface-head"
        >
          Cancel
        </button>
      </span>
    </fieldset>
  );
}
