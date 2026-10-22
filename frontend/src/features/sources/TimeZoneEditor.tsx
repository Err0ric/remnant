import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";

interface TimeZoneEditorProps {
  sourceId: string;
  value: string;
  canManage: boolean;
}

const COMMON = [
  "UTC",
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Kolkata",
  "Asia/Tokyo",
  "Australia/Sydney",
];

/** The zone for times that carry none (RFC 3164 headers, firewall local times). Only lines
 * read after a change use it; stored events keep their time. Audited source.timezone. */
export function TimeZoneEditor({ sourceId, value, canManage }: TimeZoneEditorProps) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [zone, setZone] = useState(value);
  const save = useMutation({
    mutationFn: () => api.setSourceTimezone(sourceId, zone.trim()),
    onSuccess: () => {
      setOpen(false);
      void client.invalidateQueries({ queryKey: ["source-list"] });
      void client.invalidateQueries({ queryKey: ["sources"] });
    },
  });
  if (!open) {
    return (
      <span className="flex items-center gap-2 text-sm text-text-muted">
        <span>
          Time zone <span className="font-mono">{value}</span>
        </span>
        {canManage ? (
          <button
            type="button"
            aria-label={`Change time zone of ${sourceId}`}
            onClick={() => {
              setZone(value);
              setOpen(true);
            }}
            className="text-accent-text hover:underline"
          >
            Change
          </button>
        ) : null}
      </span>
    );
  }
  return (
    <form
      aria-label={`Time zone of ${sourceId}`}
      className="flex max-w-[22rem] flex-col gap-1.5 whitespace-normal text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <label className="flex flex-col gap-1">
        <span className="text-text-secondary">Time zone (IANA name)</span>
        <input
          list={`zones-${sourceId}`}
          value={zone}
          onChange={(e) => setZone(e.target.value)}
          className="h-8 rounded border border-border-strong bg-inset px-2 font-mono"
        />
        <datalist id={`zones-${sourceId}`}>
          {COMMON.map((z) => (
            <option key={z} value={z} />
          ))}
        </datalist>
      </label>
      <span className="text-text-muted">
        Used for times that carry no zone. Only events read from now on take it.
      </span>
      {save.error ? (
        <span role="alert" className="text-danger">
          {save.error instanceof ApiError ? save.error.message : "That did not work"}
        </span>
      ) : null}
      <span className="flex gap-2">
        <button
          type="submit"
          disabled={!zone.trim() || save.isPending}
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
