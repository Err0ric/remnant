import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

interface ModelWaitProps {
  providerId: string;
  /** What the model is doing, e.g. "Writing SQL" or "Explaining". */
  label: string;
  pending: boolean;
  onCancel: () => void;
}

/**
 * While a model call is pending (ADR-0028 row 10): the time so far, and once it has taken a
 * couple of seconds, whether the model is busy with other requests, with Cancel.
 */
export function ModelWait({ providerId, label, pending, onCancel }: ModelWaitProps) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!pending) return;
    setElapsed(0);
    const started = Date.now();
    const timer = window.setInterval(
      () => setElapsed(Math.round((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [pending]);
  const queue = useQuery({
    queryKey: ["provider-queue", providerId],
    queryFn: () => api.providerQueue(providerId),
    enabled: pending && elapsed >= 2 && providerId !== "",
    refetchInterval: 2000,
  });
  if (!pending || elapsed < 2) return null;
  const q = queue.data;
  const waiting = q !== undefined && q.slots !== null && (q.waiting > 0 || q.running > q.slots);
  return (
    <p role="status" className="flex flex-wrap items-center gap-3 text-sm text-text-secondary">
      <span>
        {waiting ? "Model busy, waiting for a free slot" : `${label}…`} {elapsed} s
      </span>
      <button
        type="button"
        onClick={onCancel}
        className="h-7 rounded border border-border-strong px-3 text-text hover:bg-surface-head"
      >
        Cancel
      </button>
    </p>
  );
}

/** True for the "model busy" answer (HTTP 503, code provider_busy). */
export function isModelBusy(err: unknown): boolean {
  return err instanceof ApiError && err.code === "provider_busy";
}

/** True when the request was cancelled in the browser. */
export function isAborted(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}
