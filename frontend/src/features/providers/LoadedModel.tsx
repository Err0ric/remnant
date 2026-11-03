import { useQuery } from "@tanstack/react-query";
import { api, type ProviderRuntime } from "@/lib/api";

const WHERE: Record<ProviderRuntime["models"][number]["placement"], string> = {
  gpu: "on GPU",
  cpu: "on CPU only",
  split: "split between GPU and CPU",
};

function gb(bytes: number): string {
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

/** What a local Ollama server has loaded now (owner, 2026-11-03): GPU or CPU and the
 * context length, from Ollama's /api/ps, so it is visible without curl. Shows nothing for
 * a cloud provider or a server that does not report it. */
export function LoadedModel({ providerId }: { providerId: string }) {
  const q = useQuery({
    queryKey: ["provider-runtime", providerId],
    queryFn: () => api.providerRuntime(providerId),
    refetchInterval: 60_000,
  });
  const r = q.data;
  if (!r?.available) return null;
  const mine = r.models.find((m) => m.configured);
  const others = r.models.filter((m) => !m.configured);
  return (
    <div className="mt-1 text-text-secondary" aria-label="Loaded model">
      {mine ? (
        <p>
          Loaded {WHERE[mine.placement]}
          {mine.placement === "split" ? ` (${mine.gpu_percent}% on GPU)` : ""},{" "}
          {gb(mine.size_bytes)}
          {mine.context ? `, context ${mine.context.toLocaleString()} tokens` : ""}
        </p>
      ) : (
        <p>Not loaded now; Ollama loads it on the next question.</p>
      )}
      {others.length ? (
        <p className="text-text-muted">
          Also loaded: {others.map((m) => `${m.name} (${WHERE[m.placement]})`).join(", ")}
        </p>
      ) : null}
    </div>
  );
}
