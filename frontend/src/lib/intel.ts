import type { IntelHit } from "@/lib/api";

/** "Listed by Feodo Tracker: QakBot botnet C2": one line per listing (ADR-0023 row 7). */
export function intelLine(hit: IntelHit): string {
  const seen = hit.last_seen ? `, last seen ${hit.last_seen.slice(0, 10)}` : "";
  return `Listed by ${hit.feed}: ${hit.threat}${seen}`;
}
