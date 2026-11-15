import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { needsYouRows } from "@/features/dashboard/NeedsYou";
import type { Overview } from "@/lib/api";
import { SOURCE, mockApi } from "./mockApi";

/** Old events delivered just now (an offline queue, an import): the pages say how long the
 * source has been quiet from its newest dated event, and "Last received" stays the arrival. */
const NOW = "2026-10-10T12:30:00+00:00";
const ARRIVED = "2026-10-10T12:29:35+00:00"; // 25 s ago
const DATED = "2026-10-08T12:30:00+00:00"; // 2 days ago
const HOURS = Array.from({ length: 24 }, (_, i) =>
  new Date(Date.UTC(2026, 9, 9, 13 + i)).toISOString().replace(".000Z", "+00:00"),
);

const row = (source_id: string, over: Record<string, unknown>) => ({
  source_id,
  state: "reading",
  last_event_at: ARRIVED,
  newest_event_at: DATED,
  files_waiting: 0,
  records_skipped: 0,
  error: null,
  rate_per_min: 0,
  ...over,
});

const OVERVIEW = {
  generated_at: NOW,
  hours: HOURS,
  volume: [],
  sources: [
    row("collector_unmarked", { condition: "quiet" }),
    row("collector_marked", {
      condition: "healthy",
      quiet_ok_days: 7,
      quiet_ok: true,
      idle: true,
    }),
  ],
  source_summary: {
    total: 2,
    healthy: 1,
    quiet: [{ source_id: "collector_unmarked", last_event_at: DATED }],
    gaps: 0,
    longest_wait: null,
    idle: 1,
  },
  detections: [],
  paused: [],
  alerts: null,
  events_24h: 0,
  history_days: 7,
  events_compared_24h: 0,
  events_usual_24h: null,
  new_sources: [],
};

const pushSource = (source_id: string, days: number | null) => ({
  ...SOURCE,
  source_id,
  kind: "otlp",
  format: "json",
  path: "",
  quiet_ok_days: days,
  status: { ...SOURCE.status, last_event_at: ARRIVED },
});

async function renderAt(path: string) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
  const base = spy.getMockImplementation() as typeof fetch;
  const json = (body: unknown) =>
    new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  spy.mockImplementation(async (input, init) => {
    const u = String(input);
    if ((init?.method ?? "GET") === "GET") {
      if (u.endsWith("/api/overview")) return json(OVERVIEW);
      if (u.endsWith("/api/sources"))
        return json([pushSource("collector_unmarked", null), pushSource("collector_marked", 7)]);
    }
    return base(input, init);
  });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
}

afterEach(() => vi.restoreAllMocks());

describe("Quiet durations on the pages count from the newest dated event", () => {
  it("Health says Quiet 2 d and the idle sentence, and Last received stays the arrival", async () => {
    await renderAt("/health");
    const quiet = await vi.waitFor(() => {
      const el = document.getElementById("flow-collector_unmarked");
      if (!el) throw new Error("not yet");
      return el;
    });
    expect(within(quiet).getByText("Quiet 2 d")).toBeInTheDocument();
    // The Last received column is when the last record arrived, not the event's date.
    expect(quiet.querySelector("time")).toHaveAttribute("datetime", ARRIVED);
    const idle = document.getElementById("flow-collector_marked") as HTMLElement;
    expect(within(idle).getByText("Idle")).toBeInTheDocument();
    expect(within(idle).getByText("No events for 2 d (normal for this source)")).toBeVisible();
    expect(idle.querySelector("time")).toHaveAttribute("datetime", ARRIVED);
    expect(await screen.findByText(/1 quiet: collector_unmarked 2 d/)).toBeInTheDocument();
  });

  it("Sources says Idle: No events for 2 d", async () => {
    await renderAt("/sources");
    expect(
      await screen.findByText("Idle: No events for 2 d (normal for this source)"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/No events for 25 s/)).toBeNull();
  });

  it("times a Needs you row by when the source went quiet, not the last arrival", () => {
    const o = {
      ...OVERVIEW,
      volume: [
        {
          source_id: "collector_unmarked",
          counts: HOURS.map(() => 0),
          typical: HOURS.map(() => null),
          marks: HOURS.map(() => ""),
          total: 0,
          gaps: [{ start: HOURS[0], end: null, hours: 23, ongoing: true, others_flowing: true }],
        },
      ],
    } as unknown as Overview;
    const rows = needsYouRows(undefined, [], o);
    expect(rows.map((r) => [r.subject?.value, r.at])).toEqual([["collector_unmarked", DATED]]);
  });
});
