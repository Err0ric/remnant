import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pin as PinIcon } from "lucide-react";
import { ApiError, api, type Pin } from "@/lib/api";
import { MAX_PINS, PINS_KEY, usePins } from "@/lib/pins";

interface PinButtonProps {
  kind: Pin["kind"];
  id: string;
  /** The target's name, for the button's accessible name. */
  name: string;
}

/** Pin or Unpin a saved search or dashboard to the rail's Pinned region (D259). A plain
 * secondary button; pressed while pinned. With five pins it waits until one is unpinned. */
export function PinButton({ kind, id, name }: PinButtonProps) {
  const client = useQueryClient();
  const pins = usePins();
  const list = pins.data ?? [];
  const pinned = list.some((p) => p.kind === kind && p.id === id);
  const full = !pinned && list.length >= MAX_PINS;
  const toggle = useMutation({
    mutationFn: async () => {
      if (pinned) await api.unpin(kind, id);
      else await api.pin(kind, id);
    },
    onSettled: () => void client.invalidateQueries({ queryKey: PINS_KEY }),
  });
  const failed = toggle.error instanceof ApiError ? toggle.error.message : null;
  return (
    <button
      type="button"
      aria-label={`${pinned ? "Unpin" : "Pin"} ${name}`}
      aria-pressed={pinned}
      disabled={!pins.isSuccess || full || toggle.isPending}
      title={full ? `At most ${MAX_PINS} pins. Unpin one first.` : (failed ?? undefined)}
      onClick={() => toggle.mutate()}
      className="inline-flex items-center gap-1 px-2 py-0.5 text-text-secondary hover:text-text disabled:text-text-muted"
    >
      <PinIcon size={14} aria-hidden className="shrink-0" />
      {pinned ? "Unpin" : "Pin"}
    </button>
  );
}
