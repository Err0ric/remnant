import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, type AlertPause, type VendorSeverity } from "@/lib/api";

const LEVELS: { value: VendorSeverity; label: string }[] = [
  { value: "critical", label: "Critical" },
  { value: "high", label: "High and above" },
  { value: "medium", label: "Medium and above" },
  { value: "low", label: "Low and above" },
  { value: "info", label: "All" },
];

export function heldText(pause: AlertPause): string {
  const parts = Object.entries(pause.held).map(([k, n]) => `${n} ${k}`);
  return parts.length ? `${parts.join(", ")} held` : "none held yet";
}

interface VendorAlertNotifyProps {
  sourceId: string;
  pause: AlertPause | null | undefined;
  canManage: boolean;
}

/** A vendor alert source's cap pause, and the admin switch that sends its alerts (D231). */
export function VendorAlertNotify({ sourceId, pause, canManage }: VendorAlertNotifyProps) {
  const [open, setOpen] = useState(false);
  const paused = pause ? (
    <span className="text-sm text-warn">
      Over 100 new alerts an hour: below High are stored, not raised ({heldText(pause)})
    </span>
  ) : null;
  if (!canManage) return paused;
  return (
    <>
      {paused}
      {open ? (
        <NotifyEditor sourceId={sourceId} onClose={() => setOpen(false)} />
      ) : (
        <button
          type="button"
          aria-label={`Vendor alert messages for ${sourceId}`}
          onClick={() => setOpen(true)}
          className="self-start whitespace-nowrap text-sm text-accent-text hover:underline"
        >
          Vendor alert messages
        </button>
      )}
    </>
  );
}

interface NotifyEditorProps {
  sourceId: string;
  onClose: () => void;
}

function NotifyEditor({ sourceId, onClose }: NotifyEditorProps) {
  const client = useQueryClient();
  const targets = useQuery({ queryKey: ["alert-targets"], queryFn: api.alertTargets });
  const saved = useQuery({
    queryKey: ["alert-notify", sourceId],
    queryFn: () => api.alertNotify(sourceId),
  });
  // null until the admin changes something; until then the saved setting applies.
  const [notify, setNotify] = useState<boolean | null>(null);
  const [picked, setPicked] = useState<string[] | null>(null);
  const [level, setLevel] = useState<VendorSeverity | null>(null);
  const on = notify ?? saved.data?.notify ?? false;
  const chosen = picked ?? saved.data?.target_ids ?? [];
  const min = level ?? saved.data?.min_severity ?? "high";
  const save = useMutation({
    mutationFn: () =>
      api.setAlertNotify(sourceId, { notify: on, target_ids: chosen, min_severity: min }),
    onSuccess: () => {
      onClose();
      void client.invalidateQueries({ queryKey: ["alert-notify", sourceId] });
    },
  });
  const toggle = (id: string) =>
    setPicked(chosen.includes(id) ? chosen.filter((t) => t !== id) : [...chosen, id]);

  return (
    <fieldset className="mt-1 flex max-w-[22rem] flex-col gap-1.5 whitespace-normal text-sm">
      <legend className="sr-only">Vendor alert messages for {sourceId}</legend>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={on} onChange={(e) => setNotify(e.target.checked)} />
        <span>Notify alert targets</span>
      </label>
      <span className="text-text-muted">
        Off by default: vendors usually send their own messages. When on, a new alert or a rise in
        severity is sent once.
      </span>
      <label className="flex flex-col gap-0.5">
        <span className="text-text-secondary">Minimum severity</span>
        <select
          value={min}
          disabled={!on}
          onChange={(e) => setLevel(e.target.value as VendorSeverity)}
          className="h-7 rounded border border-border-strong bg-surface px-1 disabled:opacity-50"
        >
          {LEVELS.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </select>
      </label>
      <div className="flex flex-col gap-0.5">
        <span className="text-text-secondary">Send to</span>
        {(targets.data ?? []).length === 0 && !targets.isPending ? (
          <span className="text-text-muted">
            No alert targets yet; add one under Alert targets.
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
          These targets also get a message when the source goes over 100 new alerts an hour, and one
          when it drops back saying how many were held. With none chosen, every alert target gets
          them.
        </span>
      </div>
      {save.error ? (
        <span role="alert" className="text-danger">
          {save.error instanceof ApiError ? save.error.message : "Could not save"}
        </span>
      ) : null}
      <span className="flex gap-2">
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending || saved.isPending}
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
