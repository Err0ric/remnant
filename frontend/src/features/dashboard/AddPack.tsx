import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";

const EVERY: Record<string, string> = { hourly: "hourly", daily: "daily" };

/** Add a pack (ADR-0033 row 5): tick queries from a library pack; each becomes your
 * private saved search, a private schedule with the suggested interval and flag, and a
 * panel in a section named after its group. Everything made is ordinary and editable. */
export function AddPack({ dashboardId }: { dashboardId: string }) {
  const client = useQueryClient();
  const lib = useQuery({ queryKey: ["library"], queryFn: api.library });
  const [packId, setPackId] = useState("");
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [done, setDone] = useState<string | null>(null);
  const pack = lib.data?.packs.find((p) => p.id === packId) ?? null;
  const add = useMutation({
    mutationFn: async () => {
      const out = await api.addPack(packId, [...ticked], dashboardId);
      // Run each once so the panels fill now; a failure shows on its panel.
      await Promise.allSettled(out.added.map((a) => api.runSchedule(a.schedule_id)));
      return out;
    },
    onSuccess: async (out) => {
      setDone(
        `Added ${out.added.length} ${out.added.length === 1 ? "panel" : "panels"} from ${pack?.name ?? "the pack"}.`,
      );
      setTicked(new Set());
      setPackId("");
      await Promise.all([
        client.invalidateQueries({ queryKey: ["dashboards"] }),
        client.invalidateQueries({ queryKey: ["schedules"] }),
        client.invalidateQueries({ queryKey: ["searches"] }),
        client.invalidateQueries({ queryKey: ["library"] }),
      ]);
    },
  });
  const pick = (id: string) => {
    setPackId(id);
    setDone(null);
    const p = lib.data?.packs.find((x) => x.id === id);
    setTicked(new Set(p ? p.queries.map((q) => q.id) : []));
  };
  return (
    <fieldset aria-label="Add a pack" className="flex flex-col gap-2 border-t border-border pt-3">
      <legend className="sr-only">Add a pack</legend>
      <label className="flex flex-col gap-1">
        <span className="text-text-secondary">Add a pack from the query library</span>
        <select
          aria-label="Pack"
          value={packId}
          onChange={(e) => pick(e.target.value)}
          className="h-8 w-56 max-w-full rounded border border-border-strong bg-inset px-2"
        >
          <option value="">
            {lib.data && !lib.data.packs.length ? "No pack fits your sources yet" : "Pick a pack"}
          </option>
          {(lib.data?.packs ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} ({p.queries.length})
            </option>
          ))}
        </select>
      </label>
      {pack ? (
        <>
          <ul aria-label={`Queries in ${pack.name}`} className="flex flex-col gap-1">
            {pack.queries.map((q) => (
              <li key={q.id}>
                <label className="flex items-baseline gap-2">
                  <input
                    type="checkbox"
                    checked={ticked.has(q.id)}
                    onChange={(e) => {
                      const next = new Set(ticked);
                      if (e.target.checked) next.add(q.id);
                      else next.delete(q.id);
                      setTicked(next);
                    }}
                  />
                  <span>
                    <span className="font-semibold">{q.name}</span>
                    <span className="text-text-muted">
                      {" "}
                      {q.group}, {EVERY[q.suggested_schedule ?? "daily"]}
                      {q.flag ? `, flags ${q.flag}` : ""}
                      {q.my_copy ? ", uses your copy" : ""}
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <button
            type="button"
            disabled={!ticked.size || add.isPending}
            onClick={() => add.mutate()}
            className="h-8 self-start rounded border border-border px-2 hover:bg-surface-head disabled:opacity-50"
          >
            {add.isPending
              ? "Adding…"
              : `Add ${ticked.size} ${ticked.size === 1 ? "panel" : "panels"}`}
          </button>
        </>
      ) : null}
      {done ? (
        <p role="status" className="text-text-secondary">
          {done} Each is a private saved search and schedule you can change.
        </p>
      ) : null}
      {add.error ? (
        <p role="alert" className="text-danger">
          {add.error instanceof ApiError ? add.error.message : "That did not work"}
        </p>
      ) : null}
    </fieldset>
  );
}
