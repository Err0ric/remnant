import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AddressHolders } from "@/features/search/AddressHolders";

afterEach(() => vi.restoreAllMocks());

function renderWith(body: unknown) {
  const spy = vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(
      new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } }),
    );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <AddressHolders ip="10.20.1.6" at="2026-10-10T11:00:00Z" />
    </QueryClientProvider>,
  );
  return { spy, view };
}

describe("AddressHolders (ADR-0020 row 1)", () => {
  it("names who had the address at the event's time", async () => {
    const { spy } = renderWith({
      ip: "10.20.1.6",
      at: "2026-10-10T11:00:00Z",
      max_age_hours: 12,
      holders: [
        { kind: "user", name: "bob", last_seen: "2026-10-10T10:45:00Z", events: 1 },
        { kind: "host", name: "WS-0042", last_seen: "2026-10-10T10:45:00Z", events: 1 },
      ],
    });
    expect(await screen.findByText("bob")).toBeVisible();
    expect(screen.getByText("WS-0042")).toBeVisible();
    expect(String(spy.mock.calls[0]?.[0])).toContain(
      "/api/addresses/10.20.1.6?at=2026-10-10T11%3A00%3A00Z",
    );
  });

  it("shows nothing when nobody is known", async () => {
    const { view, spy } = renderWith({ ip: "10.20.1.6", at: "x", max_age_hours: 12, holders: [] });
    await vi.waitFor(() => expect(spy).toHaveBeenCalled());
    expect(view.container.textContent).toBe("");
  });
});
