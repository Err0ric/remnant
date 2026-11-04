import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, type AlertItem, type CloseReason } from "@/lib/api";

const NOTE_REQUIRED: CloseReason[] = ["false_positive"];
const MUTE_DAYS = [0, 7, 30] as const;

interface CloseFormProps {
  item: AlertItem;
  reasons: Record<CloseReason, string>;
  isAdmin: boolean;
  onDone: () => void;
}

/** Close with a reason (ADR-0043 rows 16 to 18): Expected, Approved, False positive (note
 * required), or Resolved. Approved also marks the agent, service, or MCP server reviewed.
 * Admins may also mute alerts like this one for 7 or 30 days. */
export function CloseForm({ item, reasons, isAdmin, onDone }: CloseFormProps) {
  const client = useQueryClient();
  const [reason, setReason] = useState<CloseReason | null>(null);
  const [note, setNote] = useState("");
  const [days, setDays] = useState<0 | 7 | 30>(0);
  // AI Watch service and MCP server alerts: closing can decide the review status too
  // (owner, 2026-10-29). Admins only, as on AI usage.
  const reviewable =
    item.kind === "ai_watch" &&
    (item.subject.startsWith("service:") || item.subject.startsWith("mcp:"));
  const [review, setReview] = useState<"approved" | "not_approved" | null>(null);
  const needsNote = reason !== null && NOTE_REQUIRED.includes(reason);
  const close = useMutation({
    mutationFn: async () => {
      if (!reason) return;
      // Approved approves the service or MCP server itself (ADR-0043 row 17).
      await api.closeAlert(
        item.item_id,
        reason,
        note.trim() || null,
        reason === "approved" ? null : review,
      );
      if (days !== 0) await api.muteAlert(item.item_id, days);
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["alerts"] });
      if (review || reason === "approved") {
        await client.invalidateQueries({ queryKey: ["ai-usage"] });
        await client.invalidateQueries({ queryKey: ["ai-watch"] });
      }
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
      {reviewable && isAdmin && reason !== "approved" ? (
        <fieldset className="grid gap-1">
          <legend className="mb-1 text-sm font-semibold">
            Review status of this {item.subject.startsWith("mcp:") ? "MCP server" : "service"}
          </legend>
          {(
            [
              [null, "Leave unreviewed"],
              ["approved", "Approve"],
              ["not_approved", "Not approved"],
            ] as const
          ).map(([value, label]) => (
            <label key={label} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name={`review-${item.item_id}`}
                checked={review === value}
                onChange={() => setReview(value)}
              />
              {label}
            </label>
          ))}
          {review === null ? (
            <span className="text-sm text-text-muted">
              It stays on AI Watch as not reviewed until someone decides.
            </span>
          ) : null}
        </fieldset>
      ) : reviewable ? (
        <p className="text-sm text-text-muted">
          An administrator sets the review status; closing leaves it not reviewed.
        </p>
      ) : null}
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
              : reason === "resolved"
                ? "What was done"
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
            onChange={(e) => setDays(Number(e.target.value) as 0 | 7 | 30)}
            className="h-7 rounded border border-border bg-surface px-1"
          >
            {MUTE_DAYS.map((d) => (
              <option key={d} value={d}>
                {d === 0 ? "No" : `For ${d} days`}
              </option>
            ))}
          </select>
          {days > 0 ? (
            <span className="text-text-muted">
              New ones like it close themselves as Muted and stay on the Closed list.
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
