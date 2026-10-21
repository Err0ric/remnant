import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, api } from "@/lib/api";
import { navigate } from "@/lib/route";

interface HandoffPanelProps {
  eventIds: string[];
  onClose: () => void;
}

/** Send selected events to an alert target with a note (ADR-0024). */
export function HandoffPanel({ eventIds, onClose }: HandoffPanelProps) {
  const targets = useQuery({ queryKey: ["alert-targets"], queryFn: api.alertTargets });
  const [targetId, setTargetId] = useState("");
  const [note, setNote] = useState("");
  const send = useMutation({
    mutationFn: (target: string) => api.handoff({ target_id: target, event_ids: eventIds, note }),
  });
  const chosen = targetId || targets.data?.[0]?.target_id || "";
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (chosen) send.mutate(chosen);
  };
  const done = send.data;
  const count = eventIds.length;

  return (
    <form
      aria-label="Send events"
      onSubmit={submit}
      className="flex flex-col gap-2.5 border-b border-border px-3.5 py-3 text-sm"
    >
      <div className="flex items-baseline gap-2">
        <h3 className="font-semibold">
          Send {count} {count === 1 ? "event" : "events"}
        </h3>
        <span className="text-text-muted">
          to a ticket system, chat channel, or mailbox you set up as an alert target
        </span>
        <button
          type="button"
          onClick={onClose}
          className="ml-auto text-text-secondary hover:text-text"
        >
          Close
        </button>
      </div>
      {targets.data && targets.data.length === 0 ? (
        <p className="text-text-secondary">
          No alert targets yet.{" "}
          <button
            type="button"
            onClick={() => navigate("alerts")}
            className="text-accent-text hover:underline"
          >
            Add one under Alert targets
          </button>
        </p>
      ) : done ? (
        <p role="status" className="text-text">
          Queued {done.sent} {done.sent === 1 ? "event" : "events"}.
          {done.withheld_local_only
            ? ` ${done.withheld_local_only} from local-only sources stayed here: that target is outside your network.`
            : ""}
          {done.not_found ? ` ${done.not_found} could not be found.` : ""}
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2">
              <span className="text-text-secondary">To</span>
              <select
                value={chosen}
                onChange={(e) => setTargetId(e.target.value)}
                className="h-8 rounded border border-border-strong bg-inset px-2"
              >
                {(targets.data ?? []).map((t) => (
                  <option key={t.target_id} value={t.target_id}>
                    {t.name} ({t.kind})
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="flex flex-col gap-1">
            <span className="text-text-secondary">Note</span>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={2000}
              rows={3}
              placeholder="What should whoever picks this up know?"
              className="max-w-2xl rounded border border-border-strong bg-inset px-2.5 py-1.5"
            />
          </label>
          <p className="max-w-2xl text-xs text-text-muted">
            Webhooks get each event with its raw line; chat and email get a short list with event
            ids. Events from local-only sources go only to targets on your own network.
          </p>
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={!chosen || send.isPending}
              className="h-8 rounded bg-accent px-3 font-semibold text-white hover:brightness-110 disabled:opacity-40"
            >
              {send.isPending ? "Sending…" : "Send"}
            </button>
            {send.error ? (
              <span role="alert" className="text-danger">
                {send.error instanceof ApiError ? send.error.message : "Could not send"}
              </span>
            ) : null}
          </div>
        </>
      )}
    </form>
  );
}
