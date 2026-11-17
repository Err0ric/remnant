import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AlertMetrics } from "@/lib/api";
import { HandlingPage, closedIn, plainDuration } from "@/features/alerts/HandlingPage";

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

const spread = (count: number, median_s: number | null, p90_s: number | null) => ({
  count,
  median_s,
  p90_s,
});

const METRICS: AlertMetrics = {
  start: "2026-11-01T00:00:00+00:00",
  end: "2026-11-03T12:00:00+00:00",
  timezone: "UTC",
  thresholds: { critical: 1, high: 3, medium: 7, low: 30 },
  time_to_close: spread(4, 187_200, 360_000),
  time_to_close_by_severity: {
    high: spread(1, 3_600, 3_600),
    medium: spread(3, 187_200, 300_000),
    other: spread(0, null, null),
  },
  closed_not_timed: 2,
  days: [
    { day: "2026-11-01", opened: 3, closed: 1 },
    { day: "2026-11-02", opened: 0, closed: 4 },
    { day: "2026-11-03", opened: 2, closed: 1 },
  ],
  opened: 5,
  closed: 6,
  open: 3,
  open_by_severity: { high: 2, medium: 0, other: 1 },
  open_by_kind: { rule: 1, schedule: 0, ai_watch: 2, gap: 0 },
  overdue: 1,
  overdue_by_severity: { high: 1, medium: 0, other: 0 },
  restricted: false,
};

function show(body: unknown, status = 200, address = "/alerts/handling") {
  window.history.replaceState(null, "", address);
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation((url) =>
    String(url).includes("/api/alerts/metrics")
      ? Promise.resolve(
          new Response(JSON.stringify(body), {
            status,
            headers: { "Content-Type": "application/json" },
          }),
        )
      : new Promise<Response>(() => {}),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <HandlingPage />
    </QueryClientProvider>,
  );
  return spy;
}

describe("Alerts > Handling (D261)", () => {
  it("says durations in plain words", () => {
    expect(plainDuration(30)).toBe("under a minute");
    expect(plainDuration(45 * 60)).toBe("45 min");
    expect(plainDuration(3 * 3600 + 5 * 60)).toBe("3 h 5 min");
    expect(plainDuration(2 * 86_400)).toBe("2 d");
    expect(plainDuration(187_200)).toBe("2 d 4 h");
  });

  it("asks for the last 30 days by default and shows the tiles", async () => {
    const spy = show(METRICS);
    expect((await screen.findAllByText("2 d 4 h")).length).toBe(2); // the tile and Medium
    const url = String(spy.mock.calls.find(([u]) => String(u).includes("metrics"))?.[0]);
    expect(url).toMatch(/\/api\/alerts\/metrics\?start=/);
    const strip = screen.getByRole("region", { name: "Alert handling numbers" });
    expect(within(strip).getByText("4 d 4 h")).toBeTruthy(); // 90th percentile
    expect(within(strip).getByText("High 1 (over 3 days)")).toBeTruthy();
    expect(
      within(strip).getByText("2 closed by the server or with no close time, not counted"),
    ).toBeTruthy();
    expect(within(strip).getByText("5 opened, 6 closed in the last 30 days")).toBeTruthy();
  });

  it("links counts to the Queue with the filter the list supports", async () => {
    show(METRICS);
    const high = await screen.findByRole("link", { name: "2 open, High severity. Open the Queue" });
    expect(high.getAttribute("href")).toBe("/alerts#sev=high");
    const none = screen.getByRole("link", { name: "1 open, None severity. Open the Queue" });
    expect(none.getAttribute("href")).toBe("/alerts#sev=none");
    const ai = screen.getByRole("link", { name: "2 open, AI Watch. Open the Queue" });
    expect(ai.getAttribute("href")).toBe("/alerts#cat=ai");
    fireEvent.click(ai);
    expect(window.location.pathname + window.location.hash).toBe("/alerts#cat=ai");
    // The median opens the alerts closed in the same window.
    const median = screen.getByRole("link", { name: /^Time to close, median/ });
    expect(median.getAttribute("href")).toBe("/alerts#state=closed&time=30d");
  });

  it("draws opened and closed by day", async () => {
    show(METRICS);
    const chart = await screen.findByRole("img", { name: /Alerts opened and closed per day/ });
    expect(chart.getAttribute("aria-label")).toContain("5 opened, 6 closed");
    expect(screen.getByText("Opened 5")).toBeTruthy();
    expect(screen.getByText("Closed 6")).toBeTruthy();
  });

  it("draws the counts as bars side by side, never a curve or a value below zero (owner, 2026-11-16)", async () => {
    show(METRICS);
    const chart = await screen.findByRole("img", { name: /Alerts opened and closed per day/ });
    expect(chart.querySelector("svg path")).toBeNull();
    const bars = [...chart.querySelectorAll<HTMLElement>("[data-bar]")];
    // Three days, an opened and a closed bar each.
    expect(bars.map((b) => `${b.dataset.bar} ${b.dataset.value}`)).toEqual([
      "opened 3",
      "closed 1",
      "opened 0",
      "closed 4",
      "opened 2",
      "closed 1",
    ]);
    for (const b of bars) {
      const h = parseFloat(b.style.height);
      expect(h).toBeGreaterThanOrEqual(0);
      expect(h).toBeLessThanOrEqual(100);
    }
    // The tallest bar is the real top value on an axis that starts at zero.
    expect(within(chart.parentElement as HTMLElement).getAllByText("0").length).toBeGreaterThan(0);
    expect(bars[3]!.style.height).toBe(`${(4 / 5) * 100}%`);
    chart.focus();
    fireEvent.keyDown(chart, { key: "Home" });
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(screen.getByRole("tooltip")).toHaveTextContent("Nov 2: Closed 4, Opened 0");
  });

  it("names today's outlined bars in the legend only when today has a count", async () => {
    show(METRICS);
    await screen.findByRole("img", { name: /Alerts opened and closed per day/ });
    expect(screen.getByText("Today, so far")).toBeTruthy();
    const today = [...document.querySelectorAll<HTMLElement>("[data-bar]")].slice(-2);
    expect(today.map((b) => b.style.background)).toEqual(["transparent", "transparent"]);
  });

  it("draws a one-day window solid and names no Today, so far (one point is never still filling)", async () => {
    show(
      { ...METRICS, days: [{ day: "2026-11-03", opened: 2, closed: 1 }] },
      200,
      "/alerts/handling#time=24h",
    );
    const chart = await screen.findByRole("img", { name: /Alerts opened and closed per day/ });
    const bars = [...chart.querySelectorAll<HTMLElement>("[data-bar]")];
    expect(bars.map((b) => b.style.background)).toEqual(["var(--text-secondary)", "var(--ok)"]);
    expect(screen.queryByText("Today, so far")).toBeNull();
  });

  it("has no Today, so far entry when today has nothing", async () => {
    const days = [...METRICS.days.slice(0, 2), { day: "2026-11-03", opened: 0, closed: 0 }];
    show({ ...METRICS, days });
    await screen.findByRole("img", { name: /Alerts opened and closed per day/ });
    expect(screen.queryByText("Today, so far")).toBeNull();
  });

  it("keeps the shape while loading, never a zero", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>(() => {}));
    window.history.replaceState(null, "", "/alerts/handling");
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <HandlingPage />
      </QueryClientProvider>,
    );
    expect(screen.getAllByRole("status").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByRole("region", { name: "Opened and closed" })).toBeTruthy();
    expect(screen.queryByText("0")).toBeNull();
  });

  it("an empty window reads none closed, and restricted says so without a count", async () => {
    show({
      ...METRICS,
      time_to_close: spread(0, null, null),
      time_to_close_by_severity: {
        high: spread(0, null, null),
        medium: spread(0, null, null),
        other: spread(0, null, null),
      },
      closed_not_timed: 0,
      days: METRICS.days.map((d) => ({ ...d, opened: 0, closed: 0 })),
      opened: 0,
      closed: 0,
      open: 0,
      open_by_severity: { high: 0, medium: 0, other: 0 },
      open_by_kind: { rule: 0, schedule: 0, ai_watch: 0, gap: 0 },
      overdue: 0,
      overdue_by_severity: { high: 0, medium: 0, other: 0 },
      restricted: true,
    });
    expect((await screen.findAllByText("None closed")).length).toBe(2);
    expect(screen.getByText("No open alert is past its days")).toBeTruthy();
    expect(screen.getByText(/Some alerts are in sources you can't read/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Time to close, median/ })).toBeNull();
    // Zeros are plain text, never links: Open now 0 does not open the Queue.
    expect(screen.queryByRole("link", { name: /^Open now/ })).toBeNull();
  });

  it("a failed read says so with Retry", async () => {
    show({ detail: "boom", code: "internal" }, 500);
    expect(await screen.findByText(/Alert handling did not load/)).toBeTruthy();
    // The four tiles and the three cards; nothing is left loading.
    expect(screen.getAllByText("Could not load").length).toBe(7);
    expect(screen.queryAllByRole("status")).toHaveLength(0);
  });

  it("a Custom window keeps its ends in the Closed link", () => {
    expect(
      closedIn({ start: "2026-11-01T00:00:00+00:00", end: "2026-11-02T00:00:00+00:00" }, "custom"),
    ).toBe(
      "state=closed&time=custom&from=2026-11-01T00%3A00%3A00.000Z&to=2026-11-02T00%3A00%3A00.000Z",
    );
  });

  // An open side of Custom: the server uses 30 days before the end (or now), and the page
  // says and links the window it used, never "every close kept".
  it.each([
    ["From cleared", "/alerts/handling#time=custom"],
    ["only To set", "/alerts/handling#time=custom&to=2026-11-03T12%3A00%3A00.000Z"],
  ])("Custom with %s shows and links the window the server used", async (_, address) => {
    const spy = show(METRICS, 200, address);
    const median = await screen.findByRole("link", { name: /^Time to close, median/ });
    const asked = String(spy.mock.calls.find(([u]) => String(u).includes("metrics"))?.[0]);
    expect(asked).not.toContain("start=");
    const want = new URLSearchParams(median.getAttribute("href")!.split("#")[1]);
    expect(want.get("state")).toBe("closed");
    expect(want.get("time")).toBe("custom");
    expect(want.get("from")).toBe("2026-11-01T00:00:00.000Z");
    expect(want.get("to")).toBe("2026-11-03T12:00:00.000Z");
    const from = new Date(METRICS.start).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
    expect(screen.getByText(new RegExp(`closed by a person from ${from} to `))).toBeTruthy();
    expect(screen.queryByText(/in this range/)).toBeNull();
  });
});
