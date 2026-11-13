import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KpiStrip } from "@/features/dashboard/KpiStrip";

const kpi = (value: number, before: number | null = null) => ({
  value,
  before,
  extra: null,
  drill: null,
  extra_drill: null,
});

function show(data: { count?: unknown; identity?: unknown; watch?: unknown; overview?: unknown }) {
  vi.spyOn(globalThis, "fetch").mockImplementation(() =>
    Promise.resolve(new Response("{}", { status: 404 })),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  if (data.count) client.setQueryData(["alerts", "count"], data.count);
  client.setQueryData(["dashboard-sections", "7d", "identity"], {
    identity: data.identity ?? null,
  });
  client.setQueryData(["ai-watch", 7], data.watch ?? { cards: [], services_in_use: 0 });
  if (data.overview) client.setQueryData(["overview"], data.overview);
  return render(
    <QueryClientProvider client={client}>
      <KpiStrip window="7d" days={7} />
    </QueryClientProvider>,
  );
}

const labels = () =>
  [...document.querySelectorAll<HTMLElement>("[data-kpi]")].map((k) => k.dataset.kpi);

afterEach(() => vi.restoreAllMocks());

describe("Dashboard KPI strip (DESIGN.md 6.3, redesign build row 17)", () => {
  it("shows a tile only when the viewer has its source", () => {
    // Alerts and sources, but no Microsoft 365 and no AI use.
    show({
      count: { open: 0, restricted: false, by_severity: { high: 0, medium: 0, other: 0 } },
      overview: {
        source_summary: { total: 3, healthy: 3, quiet: [], gaps: 0, longest_wait: null },
      },
    });
    expect(labels()).toEqual(["Open alerts", "Sources healthy"]);
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
      "2 to review",
    );
    const sources = screen.getByRole("link", { name: /^Sources healthy: 6 of 8/ });
    expect(sources).toHaveClass("text-warn");
    expect(sources.closest("[data-kpi]")).toHaveTextContent("Not all sending; open Health");
    for (const tile of document.querySelectorAll("[data-kpi]"))
      expect(tile.querySelector("[data-about]")).not.toBeNull();
  });

  it("says Not set, with where to set it, while approved countries are not chosen", () => {
    show({ identity: { failed: kpi(3, null), outside: null } });
    const tile = document.querySelector(
      '[data-kpi="Sign-ins outside approved countries"]',
    ) as HTMLElement;
    expect(tile).toHaveTextContent("Not set");
    expect(tile).toHaveTextContent("Set approved countries to count these");
    expect(
      screen.getByRole("link", { name: /^Sign-ins outside approved countries: Not set/ }),
    ).toHaveAttribute("href", "/enrichment");
    // No window before to compare with: no change pill.
    expect(document.querySelector('[data-kpi="Failed sign-ins"] [data-change]')).toBeNull();
  });

  it("draws nothing when the viewer has none of the sources", () => {
    const { container } = show({});
    expect(container).toBeEmptyDOMElement();
  });
});
