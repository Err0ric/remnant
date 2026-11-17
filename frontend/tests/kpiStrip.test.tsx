import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KpiStrip } from "@/features/dashboard/KpiStrip";
import type { DashboardShape } from "@/features/dashboard/shape";

const ALL: DashboardShape = { m365: true, other: true, any: true };

const kpi = (value: number, before: number | null = null) => ({
  value,
  before,
  extra: null,
  drill: null,
  extra_drill: null,
});

interface Answers {
  count?: unknown;
  identity?: unknown;
  watch?: unknown;
  overview?: unknown;
}

/** The strip for a viewer with these sources; an answer left out is still on the way. */
function show(data: Answers, shape: DashboardShape = ALL, pending = false) {
  vi.spyOn(globalThis, "fetch").mockImplementation(() =>
    pending
      ? new Promise<Response>(() => undefined)
      : Promise.resolve(new Response("{}", { status: 404 })),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  if (data.count) client.setQueryData(["alerts", "count"], data.count);
  if (!pending) {
    client.setQueryData(["dashboard-sections", "7d", "identity"], {
      identity: data.identity ?? null,
    });
    client.setQueryData(["ai-watch", 7], data.watch ?? { cards: [], services_in_use: 0 });
  }
  if (data.overview) client.setQueryData(["overview"], data.overview);
  return render(
    <QueryClientProvider client={client}>
      <KpiStrip window="7d" days={7} shape={shape} />
    </QueryClientProvider>,
  );
}

const labels = () =>
  [...document.querySelectorAll<HTMLElement>("[data-kpi]")].map((k) => k.dataset.kpi);

afterEach(() => vi.restoreAllMocks());

describe("Dashboard KPI strip (DESIGN.md 6.3, redesign build row 17)", () => {
  it("has a tile for each of the viewer's sources, decided before any answer", () => {
    // Alerts and sources, but no Microsoft 365 and no AI use: AI services in use stays,
    // with its zero, so the strip does not change its number of tiles after the answer.
    show(
      {
        count: { open: 0, restricted: false, by_severity: { high: 0, medium: 0, other: 0 } },
        overview: {
          source_summary: { total: 3, healthy: 3, quiet: [], gaps: 0, longest_wait: null },
        },
      },
      { m365: false, other: true, any: true },
    );
    expect(labels()).toEqual(["Open alerts", "AI services in use", "Sources healthy"]);
    expect(document.querySelector('[data-kpi="AI services in use"]')).toHaveTextContent(
      "None in this window",
    );
    // A zero is muted, never green; all healthy is plain text, not the warn color.
    expect(screen.getByRole("link", { name: /^Open alerts: 0/ })).toHaveClass("text-text-muted");
    expect(screen.getByRole("link", { name: /^Sources healthy: 3 of 3/ })).toHaveClass("text-text");
  });

  it("shows every tile, in order, with the change against the window before", () => {
    show({
      count: { open: 4, restricted: false, by_severity: { high: 1, medium: 2, other: 1 } },
      identity: { failed: kpi(79, 26), outside: kpi(1, 0) },
      watch: { cards: [{ key: "services", unreviewed: 2 }], services_in_use: 6 },
      overview: {
        source_summary: { total: 8, healthy: 6, quiet: [], gaps: 0, longest_wait: null },
      },
    });
    expect(labels()).toEqual([
      "Open alerts",
      "Failed sign-ins",
      "Sign-ins outside approved countries",
      "AI services in use",
      "Sources healthy",
    ]);
    const failed = document.querySelector('[data-kpi="Failed sign-ins"]') as HTMLElement;
    expect(failed).toHaveTextContent("↑ 53");
    expect(document.querySelector('[data-kpi="AI services in use"]')).toHaveTextContent(
      "2 of them unreviewed",
    );
    const sources = screen.getByRole("link", { name: /^Sources healthy: 6 of 8/ });
    expect(sources).toHaveClass("text-warn");
    expect(sources.closest("[data-kpi]")).toHaveTextContent("Not all sending; open Health");
    for (const tile of document.querySelectorAll("[data-kpi]"))
      expect(tile.querySelector("[data-about]")).not.toBeNull();
  });

  it("says Not set, with where to set it, while approved countries are not chosen", () => {
    show(
      { identity: { failed: kpi(3, null), outside: null } },
      { m365: true, other: false, any: true },
    );
    const tile = document.querySelector(
      '[data-kpi="Sign-ins outside approved countries"]',
    ) as HTMLElement;
    expect(tile).toHaveTextContent("Not set");
    expect(tile).toHaveTextContent("Set approved countries to count these");
    expect(
      screen.getByRole("link", { name: /^Sign-ins outside approved countries: Not set/ }),
    ).toHaveAttribute("href", "/enrichment");
    // No data for the window before: "No earlier data", never a change from zero (item 9).
    const failed = document.querySelector('[data-kpi="Failed sign-ins"]') as HTMLElement;
    expect(failed.querySelector("[data-change]")).toHaveAttribute("data-change", "none");
    expect(failed).toHaveTextContent("No earlier data");
    expect(failed).not.toHaveTextContent("↑");
  });

  it("draws its full tile count before any answer, each tile a skeleton (item 27)", () => {
    show({}, ALL, true);
    expect(labels()).toEqual([
      "Open alerts",
      "Failed sign-ins",
      "Sign-ins outside approved countries",
      "AI services in use",
      "Sources healthy",
    ]);
    for (const tile of document.querySelectorAll("[data-kpi]")) {
      expect(tile.querySelector('[aria-busy="true"]')).not.toBeNull();
      expect(tile).not.toHaveTextContent(/\d/);
    }
    expect(screen.getByRole("region", { name: "Key numbers" })).toHaveAttribute("data-tiles", "5");
  });

  it("keeps a tile whose answer has nothing to count, saying Not available", () => {
    show({
      count: { open: 0, restricted: false, by_severity: { high: 0, medium: 0, other: 0 } },
      identity: { failed: kpi(3, 1), outside: kpi(0, 0) },
      overview: {
        source_summary: { total: 0, healthy: 0, quiet: [], gaps: 0, longest_wait: null },
      },
    });
    expect(labels()).toHaveLength(5);
    expect(document.querySelector('[data-kpi="Sources healthy"]')).toHaveTextContent(
      "Not available",
    );
  });

  it("has only Open alerts for a viewer with no sources", () => {
    show(
      { count: { open: 2, restricted: false, by_severity: { high: 0, medium: 2, other: 0 } } },
      {
        m365: false,
        other: false,
        any: false,
      },
    );
    expect(labels()).toEqual(["Open alerts"]);
  });
});
