import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, type AlertItem, type CloseReason } from "@/lib/api";

const NOTE_REQUIRED: CloseReason[] = ["false_positive", "follow_up"];
const MUTE_DAYS = [0, 1, 7, 14, 30];

interface CloseFormProps {
  item: AlertItem;
  reasons: Record<CloseReason, string>;
  isAdmin: boolean;
  onDone: () => void;
}

/** Close with a reason (ADR-0037 rows 14 to 16). A note is required for False positive
 * and Needs follow-up. Admins may also mute alerts like this one for up to 30 days. */
export function CloseForm({ item, reasons, isAdmin, onDone }: CloseFormProps) {
  const client = useQueryClient();
  const [reason, setReason] = useState<CloseReason | null>(null);
  const [note, setNote] = useState("");
  const [days, setDays] = useState(0);
  const needsNote = reason !== null && NOTE_REQUIRED.includes(reason);
  const close = useMutation({
    mutationFn: async () => {
      if (!reason) return;
      await api.closeAlert(item.item_id, reason, note.trim() || null);
      if (days > 0) await api.muteAlert(item.item_id, days);
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["alerts"] });
      onDone();
    },
  });
  const ready = reason !== null && (!needsNote || note.trim().length > 0);
  return (
    <form
      aria-label={`Close ${item.title}`}
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) close.mutate();
      }}
      className="grid gap-3 rounded-card border border-border bg-surface-head p-3"
    >
      <fieldset className="grid gap-1">
        <legend className="mb-1 text-sm font-semibold">Why close it?</legend>
        {(Object.keys(reasons) as CloseReason[]).map((r) => (
          <label key={r} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name={`reason-${item.item_id}`}
              checked={reason === r}
              onChange={() => setReason(r)}
            />
            {reasons[r]}
          </label>
        ))}
      </fieldset>
      <label className="grid gap-1 text-sm">
        <span>
          Note <span className="text-text-muted">{needsNote ? "(required)" : "(optional)"}</span>
        </span>
        <textarea
          value={note}
          maxLength={2000}
          rows={2}
          onChange={(e) => setNote(e.target.value)}
          placeholder={
            reason === "false_positive"
              ? "What made it a false positive, so the rule can be tuned"
              : reason === "follow_up"
                ? "What still needs doing, and by whom"
                : ""
          }
          className="rounded border border-border bg-surface px-2 py-1"
        />
      </label>
      {isAdmin ? (
        <label className="flex flex-wrap items-center gap-2 text-sm">
          <span>Mute alerts like this</span>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="h-7 rounded border border-border bg-surface px-1"
          >
            {MUTE_DAYS.map((d) => (
              <option key={d} value={d}>
                {d === 0 ? "No" : `For ${d} ${d === 1 ? "day" : "days"}`}
              </option>
            ))}
          </select>
          {days > 0 ? (
            <span className="text-text-muted">
              New ones close themselves as Muted and stay on the Closed list.
            </span>
          ) : null}
        </label>
      ) : null}
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={!ready || close.isPending}
          className="h-8 rounded bg-accent px-3 text-sm font-semibold text-white disabled:opacity-40"
        >
          Close alert
        </button>
        <button
          type="button"
          onClick={onDone}
          className="h-8 rounded px-2 text-sm hover:bg-surface"
        >
          Cancel
        </button>
        {close.isError ? (
          <span role="alert" className="text-sm text-danger">
            {close.error instanceof ApiError ? close.error.message : "Closing did not work"}
          </span>
        ) : null}
      </div>
    </form>
  );
}
