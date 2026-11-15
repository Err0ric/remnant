import type { Overview, Source } from "@/lib/api";

interface SourceState {
  id: string;
  problem: string | null; // why it needs someone, or null when flowing
  gaps: number; // gaps in 24 hours, for the note
}

/** Each enabled source: flowing, or why not. Errors and a quiet watch need someone; a gap
 * that ended is noted but the source is flowing (Health has the detail). */
/** A list from a response, or none: a body without it, or of another shape, is no list
 * (D194: a non-list here broke the whole Dashboard). */
export function listOf<T>(v: T[] | null | undefined | unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : [];
}

export function sourceStates(sources: Source[], o: Overview | undefined): SourceState[] {
  const volume = new Map(
    listOf<Overview["volume"][number]>(o?.volume).map((v) => [
      v.source_id,
      listOf<{ ongoing?: boolean; hours?: number }>(v.gaps),
    ]),
  );
  const health = new Map(
    listOf<Overview["sources"][number]>(o?.sources).map((h) => [h.source_id, h]),
  );
  const byId = new Map(listOf<Source>(sources).map((s) => [s.source_id, s]));
  const ids = [...new Set([...byId.keys(), ...health.keys()])].sort();
  return ids
    .filter((id) => byId.get(id)?.enabled ?? true)
    .map((id) => {
      const s = byId.get(id);
      const h = health.get(id);
      const gaps = volume.get(id) ?? [];
      // Marked "Quiet is normal" and inside its days (D260): silence is not being blind.
      const ongoing = h?.quiet_ok ? undefined : gaps.find((g) => g.ongoing);
      const problem =
        s?.status.state === "error" || h?.state === "error"
          ? "has errors"
          : s?.quiet?.state === "quiet" || h?.quiet_since || h?.gap_alert
            ? "stopped sending"
            : ongoing
              ? `has sent nothing for ${ongoing.hours} h`
              : null;
      return { id, problem, gaps: gaps.length };
    });
}
