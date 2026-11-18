import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, type SourceQuiet } from "@/lib/api";
import { Select } from "@/components/forms/Select";

/** Choices for "Alert if no events for" (ADR-0014 allows 5 minutes to 7 days). */
const PERIODS: { s: number; label: string }[] = [
  { s: 900, label: "15 minutes" },
  { s: 3600, label: "1 hour" },
  { s: 4 * 3600, label: "4 hours" },
  { s: 12 * 3600, label: "12 hours" },
  { s: 86400, label: "1 day" },
  { s: 3 * 86400, label: "3 days" },
  { s: 7 * 86400, label: "7 days" },
];

export function periodLabel(seconds: number): string {
  const known = PERIODS.find((p) => p.s === seconds);
  if (known) return known.label;
  if (seconds < 3600) return `${Math.round(seconds / 60)} minutes`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} hours`;
  return `${Math.round(seconds / 86400)} days`;
}

interface QuietAlertProps {
  sourceId: string;
  quiet: SourceQuiet | null | undefined;
  canManage: boolean;
  /** Every file it lists is read by this source: its quiet alert never fires (SPEC 3.5). */
  readBy?: string | null;
}

/** The quiet alert setting, for admins. */
export function QuietAlert({ sourceId, quiet, canManage, readBy }: QuietAlertProps) {
  const [open, setOpen] = useState(false);
  // Whether it is quiet now, and for how long, is the status word above ("Quiet 34 h"),
  // shown to every role; the setting itself is for admins.
  if (!canManage) return null;
  // It stores nothing by design while another source reads its files: no quiet alert.
  if (readBy) return <span className="text-sm text-text-secondary">No quiet alert</span>;
  if (open) {
    return <QuietEditor sourceId={sourceId} quiet={quiet ?? null} onClose={() => setOpen(false)} />;
  }
  return (
    <span className="flex flex-wrap items-center gap-x-2 text-sm">
      {quiet ? (
        <span className="text-text-secondary">
          Alert after {periodLabel(quiet.quiet_after_s)} quiet
        </span>
      ) : null}
      <button
        type="button"
        aria-label={`Quiet alert for ${sourceId}`}
        onClick={() => setOpen(true)}
        className="whitespace-nowrap text-accent-text hover:underline"
      >
        {quiet ? "Change" : "Alert if quiet"}
      </button>
    </span>
  );
}

interface QuietEditorProps {
  sourceId: string;
  quiet: SourceQuiet | null;
  onClose: () => void;
}

function QuietEditor({ sourceId, quiet, onClose }: QuietEditorProps) {
  const client = useQueryClient();
  const targets = useQuery({ queryKey: ["alert-targets"], queryFn: api.alertTargets });
  const watches = useQuery({ queryKey: ["source-watches"], queryFn: api.sourceWatches });
  const current = watches.data?.find((w) => w.source_id === sourceId);
  const [period, setPeriod] = useState<number | null>(quiet?.quiet_after_s ?? 3600);
  // null until the admin touches a checkbox; until then the saved targets apply.
  const [picked, setPicked] = useState<string[] | null>(null);
  const chosen = picked ?? current?.target_ids ?? [];
  const save = useMutation({
    mutationFn: () => api.setSourceWatch(sourceId, period, period === null ? [] : chosen),
    onSuccess: () => {
      onClose();
      void client.invalidateQueries({ queryKey: ["source-list"] });
      void client.invalidateQueries({ queryKey: ["source-watches"] });
    },
  });
  const toggle = (id: string) =>
    setPicked(chosen.includes(id) ? chosen.filter((t) => t !== id) : [...chosen, id]);

  return (
    <fieldset className="mt-1 flex max-w-[22rem] flex-col gap-1.5 whitespace-normal text-sm">
      <legend className="sr-only">Quiet alert for {sourceId}</legend>
      <label className="flex flex-col gap-0.5">
        <span className="text-text-secondary">Alert if no events for</span>
        <Select
          value={period === null ? "off" : String(period)}
          onChange={(v) => setPeriod(v === "off" ? null : Number(v))}
          options={[
            { value: "off", label: "Off" },
            ...PERIODS.map((p) => ({ value: String(p.s), label: p.label })),
            ...(quiet && !PERIODS.some((p) => p.s === quiet.quiet_after_s)
              ? [{ value: String(quiet.quiet_after_s), label: periodLabel(quiet.quiet_after_s) }]
              : []),
          ]}
          className="h-7"
        />
      </label>
      {period !== null ? (
        <div className="flex flex-col gap-0.5">
          <span className="text-text-secondary">Send to</span>
          {(targets.data ?? []).length === 0 && !targets.isPending ? (
            <span className="text-text-muted">
              No alert targets yet; add one under Alert targets. The change is still recorded in the
              audit log.
            </span>
          ) : null}
          {(targets.data ?? []).map((t) => (
            <label key={t.target_id} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={chosen.includes(t.target_id)}
                onChange={() => toggle(t.target_id)}
              />
              <span>{t.name}</span>
            </label>
          ))}
          <span className="text-text-muted">
            One alert when it goes quiet and one when events resume. Counts and times only, no event
            content.
          </span>
        </div>
      ) : null}
      {save.error ? (
        <span role="alert" className="text-danger">
          {save.error instanceof ApiError ? save.error.message : "Could not save"}
        </span>
      ) : null}
      <span className="flex gap-2">
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending || (period === null && !quiet)}
          className="h-7 rounded bg-accent px-3 font-semibold text-white hover:brightness-110 disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="h-7 rounded border border-border-strong px-3 hover:bg-surface-head"
        >
          Cancel
        </button>
      </span>
    </fieldset>
  );
}
