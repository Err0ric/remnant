import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Overview, OverviewSourceHealth } from "@/lib/api";
import { HealthBanner, SourcesLine } from "@/features/dashboard/Attention";
import { SystemStrip } from "@/features/health/SystemStrip";
import { sourcesSummaryText } from "@/features/health/flow";

const NOW = "2026-11-09T12:00:00+00:00";

function src(id: string, extra: Partial<OverviewSourceHealth> = {}): OverviewSourceHealth {
  return {
    source_id: id,
    state: "reading",
    last_event_at: "2026-11-09T11:59:00+00:00",
    files_waiting: 0,
    records_skipped: 0,
    error: null,
    rate_per_min: 1,
    condition: "healthy",
    ...extra,
  };
}

// Six sources, two quiet; server_events (refusals only) quiet for 6 days is not quiet.
// The condition and summary are what the server sends (backend test_source_state.py).
const OVERVIEW = {
  generated_at: NOW,
  hours: [],
  volume: [],
  sources: [
    src("lin_auth"),
    src("fw_main", { last_event_at: "2026-11-09T11:00:00+00:00" }),
    src("dns"),
    src("server_events", { last_event_at: "2026-11-03T12:00:00+00:00", quiet_expected: true }),
    src("win_dc", { last_event_at: "2026-11-07T12:00:00+00:00", condition: "quiet" }),
    src("vpn", { last_event_at: "2026-11-09T06:00:00+00:00", condition: "quiet" }),
  ],
  detections: [],
  paused: [],
  alerts: null,
  events_24h: 0,
  history_days: 7,
  events_compared_24h: 0,
  events_usual_24h: null,
  new_sources: [],
  source_summary: {
    total: 6,
    healthy: 4,
    quiet: [
      { source_id: "win_dc", last_event_at: "2026-11-07T12:00:00+00:00" },
      { source_id: "vpn", last_event_at: "2026-11-09T06:00:00+00:00" },
    ],
    gaps: 0,
    longest_wait: { source_id: "fw_main", last_event_at: "2026-11-09T11:00:00+00:00" },
  },
} satisfies Overview;

afterEach(() => vi.restoreAllMocks());

describe("one healthy count on Health and the Dashboard (handoff item 4)", () => {
  it("prints the same 4 of 6 and the same quiet list on both pages", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify(OVERVIEW), { headers: { "Content-Type": "application/json" } }),
      ),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["overview"], OVERVIEW);
    render(
      <QueryClientProvider client={client}>
        <HealthBanner />
        <SourcesLine />
        <SystemStrip
          overview={OVERVIEW}
          tally={{ summary: OVERVIEW.source_summary }}
          alerts={undefined}
          isAdmin={false}
          now={NOW}
          onEvents={() => {}}
          onSources={() => {}}
          onAttention={() => {}}
          onDelivery={() => {}}
        />
      </QueryClientProvider>,
    );
    // Not all healthy: the banner at the top says it, and the bottom line steps aside.
    const top = await screen.findByRole("region", { name: "Health needs attention" });
    expect(top).toHaveTextContent(
      "Sources 4 of 6 healthy, 2 quiet: win_dc 2 d, vpn 6 h, no gaps in 24 hours",
    );
    expect(screen.queryByRole("link", { name: /^Sources:/ })).toBeNull();
    const tile = screen.getByRole("button", { name: /^Sources/ });
    expect(tile).toHaveTextContent("4 of 6 healthy");
    expect(tile).toHaveTextContent("2 quiet: win_dc 2 d, vpn 6 h");
    for (const el of [top, tile]) expect(el).not.toHaveTextContent("server_events");
  });

  it("names the longest wait only when nothing is quiet, never a refusal-only source", () => {
    const text = sourcesSummaryText({ ...OVERVIEW.source_summary, quiet: [], healthy: 6 }, NOW);
    expect([text.headline, ...text.details]).toEqual([
      "6 of 6 healthy",
      "no gaps in 24 hours",
      "longest wait 60 min (fw_main)",
    ]);
  });
});
