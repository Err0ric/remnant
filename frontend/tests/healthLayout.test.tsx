import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Overview } from "@/lib/api";
import { SourceFlow, type FlowSource } from "@/features/health/SourceFlow";
import { SOURCE, mockApi } from "./mockApi";

/** Three listed sources: linux_sshd has a gap and win_dc an error in the overview; dns has
 * no problem. Targets can be emptied too. */
function sources(spy: ReturnType<typeof mockApi>, noTargets = false) {
  const base = spy.getMockImplementation() as typeof fetch;
  const json = (body: unknown) =>
    new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  spy.mockImplementation(async (input, init) => {
    const u = String(input);
    const get = (init?.method ?? "GET") === "GET";
    if (get && u.endsWith("/api/sources"))
      return json([SOURCE, { ...SOURCE, source_id: "win_dc" }, { ...SOURCE, source_id: "dns" }]);
    if (get && noTargets && u.endsWith("/api/alert-targets")) return json([]);
    return base(input, init);
  });
}

async function renderAt(path: string, tweak?: (spy: ReturnType<typeof mockApi>) => void) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
  tweak?.(spy);
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
  return spy;
}

afterEach(() => vi.restoreAllMocks());

const HELD = [
  "/api/overview",
  "/api/health-checks",
  "/api/alerts/lines",
  "/api/sources",
  "/api/schedules",
  "/api/alert-targets",
  "/api/enrichment",
];

describe("Health layout (D255)", () => {
  it("claims nothing while its requests are held, then shows each number", async () => {
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await renderAt("/health", (spy) => {
      const base = spy.getMockImplementation() as typeof fetch;
      spy.mockImplementation(async (input, init) => {
        const u = String(input);
        if ((init?.method ?? "GET") === "GET" && HELD.some((p) => u.includes(p))) await held;
        return base(input, init);
      });
    });
    const tabs = await screen.findByRole("navigation", { name: "Health tabs" });
    const tiles = await vi.waitFor(() => {
      const found = [...document.querySelectorAll<HTMLElement>("[data-kpi]")];
      if (found.length < 4) throw new Error("not yet");
      return found;
    });
    for (const text of ["All delivered", "Nothing needs a decision", "0 failed"])
      expect(screen.queryByText(text)).toBeNull();
    for (const tile of tiles) {
      expect(tile.querySelectorAll("[data-skeleton]")).toHaveLength(2);
      expect(tile.textContent?.replace(tile.dataset.kpi ?? "", "")).not.toMatch(/\d/);
    }
    expect(tabs.querySelector("[data-problems]")).toBeNull();
    expect(tabs.textContent).not.toMatch(/\d/);
    expect(screen.getByRole("group", { name: "Status" }).textContent).not.toMatch(/\d/);
    expect(document.querySelector("[data-filter-count]")).toBeNull();

    release();
    await vi.waitFor(() =>
      expect(document.querySelector('[data-kpi^="Alert delivery"]')).toHaveTextContent("2 failed"),
    );
    expect(document.querySelector('[data-kpi="Events, last 24 hours"]')).toHaveTextContent("70");
    expect(document.querySelector("[data-filter-count]")).toHaveTextContent(/^\d+ sources?$/);
  });

  it("puts a problem count on a tab only when it is above zero", async () => {
    await renderAt("/health", (spy) => sources(spy, true));
    const tabs = await screen.findByRole("navigation", { name: "Health tabs" });
    const tab = (name: RegExp) => within(tabs).getByRole("link", { name });
    // linux_sshd has a gap and win_dc an error: two problems, in the outlined warn tag.
    await vi.waitFor(() =>
      expect(tab(/^Sources/).querySelector("[data-problems]")).toHaveTextContent("2"),
    );
    expect(tab(/^Sources/).querySelector("[data-problems]")).toHaveClass("border-warn");
    // Delivery has no target and a paused schedule: nothing to flag, and no total either.
    await vi.waitFor(() =>
      expect(tab(/^Collectors/).querySelector("[data-problems]")).not.toBeNull(),
    );
    expect(tab(/^Delivery/).querySelector("[data-problems]")).toBeNull();
    expect(tab(/^Delivery/).textContent).toBe("Delivery");
  });

  it("lists unhealthy and needs-attention rows under Problems, in the address", async () => {
    await renderAt("/health", (spy) => sources(spy));
    const flow = await screen.findByRole("list", { name: "Sources" });
    const status = screen.getByRole("group", { name: "Status" });
    await vi.waitFor(() =>
      expect(within(status).getByRole("button", { name: /^Problems/ })).toHaveTextContent("2"),
    );
    await userEvent.click(within(status).getByRole("button", { name: /^Problems/ }));
    expect(window.location.hash).toBe("#status=problems");
    // win_dc is in error (Unhealthy), linux_sshd has a gap (Needs attention).
    expect(within(flow).getByText("win_dc")).toBeVisible();
    expect(within(flow).getByText("linux_sshd")).toBeVisible();
    expect(within(flow).queryByText("dns")).toBeNull();
    expect(document.querySelector("[data-filter-count]")).toHaveTextContent("2 of 3 sources");
    await userEvent.click(within(status).getByRole("button", { name: /^Healthy/ }));
    expect(window.location.hash).toBe("#status=healthy");
    const healthy = await screen.findByRole("list", { name: "Sources" });
    expect(within(healthy).getByText("dns")).toBeVisible();
    expect(within(healthy).queryByText("win_dc")).toBeNull();
  });

  it.each([
    [
      "the overview",
      "/api/overview",
      ["Events, last 24 hours", "Sources healthy", "Alert delivery, last 24 hours"],
    ],
    ["the newest alert", "/api/alerts/lines", ["Open alerts"]],
  ])("says when %s did not load, and claims nothing from it", async (_what, path, labels) => {
    await renderAt("/health", (spy) => {
      sources(spy);
      const base = spy.getMockImplementation() as typeof fetch;
      spy.mockImplementation(async (input, init) =>
        String(input).includes(path)
          ? new Response(JSON.stringify({ detail: "Boom" }), {
              status: 500,
              headers: { "Content-Type": "application/json" },
            })
          : base(input, init),
      );
    });
    for (const label of labels) {
      const tile = await vi.waitFor(() => {
        const t = document.querySelector(`[data-kpi="${label}"]`) as HTMLElement | null;
        if (!t || !t.textContent?.includes("Could not load")) throw new Error("not yet");
        return t;
      });
      expect(tile.querySelector("[data-skeleton]")).toBeNull();
      expect(within(tile).getByRole("button", { name: `Retry ${label}` })).toBeVisible();
    }
    expect(screen.queryByText("All delivered")).toBeNull();
    expect(screen.queryByText("Nothing needs a decision")).toBeNull();
    expect(
      await screen.findByText(/^Boom|Could not load health/, { selector: "p[role=alert]" }),
    ).toBeVisible();
    const tabs = screen.getByRole("navigation", { name: "Health tabs" });
    const status = screen.getByRole("group", { name: "Status" });
    if (path === "/api/overview") {
      // A source's level is the overview's condition: without it there are no counts.
      await screen.findByRole("list", { name: "Sources" });
      expect(
        within(tabs)
          .getByRole("link", { name: /^Sources/ })
          .querySelector("[data-problems]"),
      ).toBeNull();
      expect(status.textContent).not.toMatch(/\d/);
      expect(document.querySelector("[data-filter-count]")).toBeNull();
    } else {
      await vi.waitFor(() =>
        expect(within(status).getByRole("button", { name: /^Problems/ })).toHaveTextContent("2"),
      );
    }
  });

  it("counts damaged files under Problems and keeps the notice under every Status", async () => {
    await renderAt("/health", (spy) => {
      const base = spy.getMockImplementation() as typeof fetch;
      spy.mockImplementation(async (input, init) => {
        const res = await base(input, init);
        if (!String(input).endsWith("/api/overview")) return res;
        const body = await res.json();
        return new Response(JSON.stringify({ ...body, damaged_files: 2 }), {
          headers: { "Content-Type": "application/json" },
        });
      });
    });
    const status = await screen.findByRole("group", { name: "Status" });
    // linux_sshd's gap and the damaged files.
    await vi.waitFor(() =>
      expect(within(status).getByRole("button", { name: /^Problems/ })).toHaveTextContent("2"),
    );
    for (const choice of [/^Healthy/, /^Paused/, /^Problems/]) {
      await userEvent.click(within(status).getByRole("button", { name: choice }));
      expect(await screen.findByText(/^Data folder: 2 damaged files/)).toBeVisible();
    }
  });

  it("reads an unknown Status in the address as All", async () => {
    const { healthStatus } = await import("@/lib/route");
    expect(healthStatus(new URLSearchParams("status=problems"))).toBe("problems");
    expect(healthStatus(new URLSearchParams("status=constructor"))).toBe("all");
  });
});

const HOURS = Array.from({ length: 24 }, (_, i) =>
  new Date(Date.UTC(2026, 10, 12, 13 + i)).toISOString().replace(".000Z", "+00:00"),
);
const NOW = "2026-11-13T12:30:00+00:00";

function overview(): Overview {
  const src = (id: string, condition: string, extra: object = {}) => ({
    source_id: id,
    state: "reading",
    last_event_at: "2026-11-13T11:05:00+00:00",
    files_waiting: 0,
    records_skipped: 0,
    error: null,
    rate_per_min: 0,
    condition,
    ...extra,
  });
  return {
    generated_at: NOW,
    hours: HOURS,
    volume: [
      {
        source_id: "claude",
        counts: HOURS.map((_, i) => (i < 22 ? (i % 5) * 5 + 1 : 0)),
        typical: HOURS.map(() => null),
        marks: HOURS.map(() => ""),
        total: 82,
        gaps: [],
      },
      {
        source_id: "fw",
        counts: HOURS.map((_, i) => (i < 20 ? 9 : 0)),
        typical: HOURS.map(() => null),
        marks: HOURS.map(() => ""),
        total: 180,
        gaps: [{ start: HOURS[20], end: null, hours: 4, ongoing: true, others_flowing: true }],
      },
    ],
    sources: [
      src("claude", "quiet", { quiet_since: "2026-11-13T12:05:00+00:00" }),
      src("fw", "quiet", { quiet_since: "2026-11-13T12:05:00+00:00" }),
    ],
    detections: [],
    paused: [],
    alerts: null,
    events_24h: 262,
    history_days: 7,
    events_compared_24h: 262,
    events_usual_24h: null,
    new_sources: [],
    source_summary: { total: 2, healthy: 0, quiet: [], gaps: 1, longest_wait: null },
  } as unknown as Overview;
}

describe("Health > Sources rows (D255)", () => {
  const rows: FlowSource[] = [
    {
      source_id: "claude",
      level: "unhealthy",
      word: "Quiet 85 min",
      reason: "No events for over 1 h",
      quietNote: true,
      last: null,
    },
    {
      source_id: "fw",
      level: "unhealthy",
      word: "Quiet 85 min",
      reason: "No events for over 1 h",
      quietNote: true,
      last: null,
    },
  ];

  it("greys a source that is only quiet and keeps a gap's danger sentence once", () => {
    render(<SourceFlow overview={overview()} sources={rows} now={NOW} timeZone="UTC" />);
    const quiet = document.getElementById("flow-claude") as HTMLElement;
    expect(quiet).toHaveAttribute("data-quiet");
    expect(quiet.querySelector("[data-dot]")).toHaveClass("bg-text-muted");
    expect(within(quiet).getByText("claude")).toHaveClass("text-text-secondary");
    expect(quiet.querySelector("path")).toHaveClass("stroke-series-neutral");
    expect(within(quiet).getByText("No events for over 1 h")).toHaveClass("text-text-secondary");
    expect(quiet.querySelectorAll("p")).toHaveLength(1);

    const gap = document.getElementById("flow-fw") as HTMLElement;
    expect(gap).not.toHaveAttribute("data-quiet");
    expect(gap.querySelector("[data-dot]")).toHaveClass("bg-danger");
    expect(gap.querySelector("rect.fill-danger")).not.toBeNull();
    const sentences = [...gap.querySelectorAll("p")];
    expect(sentences).toHaveLength(1);
    expect(sentences[0]).toHaveClass("text-danger");
    expect(sentences[0]).toHaveTextContent(/^No events since .+\(4 h so far\)/);
    expect(within(gap).queryByText("No events for over 1 h")).toBeNull();
  });

  it("prints the peak in its own column, not on the plot, and the last time in local time", () => {
    render(<SourceFlow overview={overview()} sources={rows} now={NOW} timeZone="UTC" />);
    const header = screen.getByText("Peak");
    expect(header.parentElement?.textContent).toMatch(
      /^SourceStatus.*Peak24 hoursPer minuteLast received$/,
    );
    const row = document.getElementById("flow-claude") as HTMLElement;
    expect(row.querySelector("[data-peak]")).toHaveTextContent(/^21\/h/);
    const plot = row.querySelector("svg")?.parentElement as HTMLElement;
    expect(plot.textContent).not.toMatch(/peak|\/h/);
    const time = row.querySelector("time") as HTMLElement;
    expect(time).toHaveTextContent("Nov 13, 11:05 AM");
    expect(time).toHaveAttribute("title", "2026-11-13 11:05 UTC");
  });
});
