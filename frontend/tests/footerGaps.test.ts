import { describe, expect, it } from "vitest";
import type { Overview } from "@/lib/api";
import { sourceStates } from "@/features/dashboard/Attention";
import { needsYouRows } from "@/features/dashboard/NeedsYou";
import { openGaps, openGapsText } from "@/features/health/flow";

function overview(sources: Partial<Overview["sources"][number]>[]): Overview {
  return {
    generated_at: "2026-11-06T12:00:00+00:00",
    hours: [],
    volume: [],
    sources: sources.map((s) => ({
      source_id: "x",
      state: "reading",
      last_event_at: null,
      files_waiting: 0,
      records_skipped: 0,
      error: null,
      rate_per_min: 0,
      condition: s.gap_alert || s.quiet_since ? "quiet" : "healthy",
      ...s,
    })),
    detections: [],
    paused: [],
    alerts: null,
    events_24h: 0,
    history_days: 7,
    events_compared_24h: 0,
    events_usual_24h: null,
    new_sources: [],
    source_summary: { total: 0, healthy: 0, quiet: [], gaps: 0, longest_wait: null },
  } as Overview;
}

describe("footer and alerts agree (review item 3)", () => {
  const o = overview([
    { source_id: "lin_auth", last_event_at: "2026-11-06T11:59:00+00:00" },
    // Quiet 4 days with an open gap alert and no quiet watch left.
    { source_id: "server_events", last_event_at: "2026-11-02T12:00:00+00:00", gap_alert: "g1" },
    { source_id: "win_dc", last_event_at: "2026-11-06T09:00:00+00:00", gap_alert: "g2" },
  ]);

  it("counts every source with an open gap alert as a gap, longest quiet first", () => {
    const gaps = openGaps(o);
    expect(gaps.map((g) => [g.source_id, g.item_id, g.quiet])).toEqual([
      ["server_events", "g1", "4 d"],
      ["win_dc", "g2", "3 h"],
    ]);
    expect(openGapsText(gaps)).toBe("2 gaps: server_events quiet 4 d, win_dc quiet 3 h");
  });

  it("does not call a source with an open gap alert flowing", () => {
    const states = sourceStates([], o);
    expect(states.filter((s) => !s.problem).map((s) => s.id)).toEqual(["lin_auth"]);
    expect(states.find((s) => s.id === "server_events")?.problem).toBe("stopped sending");
  });
});

describe("Needs you banner keeps its inputs (handoff item 4, owner rule 5)", () => {
  it("lists no source that is quiet only in the shared count", () => {
    // win_dc sent nothing in 24 hours with no watch or alert: quiet in the shared count
    // and on Health, but the list shows only errors, stopped sources, and ongoing gaps.
    const o = overview([
      { source_id: "dns", state: "error", condition: "error" },
      { source_id: "win_dc", last_event_at: "2026-11-04T12:00:00+00:00", condition: "quiet" },
    ]);
    const rows = needsYouRows(undefined, [], o);
    expect(rows.map((r) => [r.order, r.kind, r.title])).toEqual([
      [1, "Source error", "dns has errors"],
    ]);
  });
});
