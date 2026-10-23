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

describe("AddressHolders (ADR-0029)", () => {
  it("says who had the address and how each was matched, assumed ends labelled", async () => {
    const { spy } = renderWith({
      ip: "10.20.1.6",
      at: "2026-10-10T11:00:00Z",
      max_age_hours: 24,
      holders: [],
      spans: [
        {
          kind: "dhcp",
          start: "2026-10-10T08:55:00Z",
          end: "2026-10-11T08:55:00Z",
          capped: true,
          person: null,
          machine: "WS-0042",
          mac: "00:00:5e:00:53:0a",
          source: "fw",
        },
        {
          kind: "signin",
          start: "2026-10-10T09:02:00Z",
          end: null,
          capped: false,
          person: "bob@example.com",
          machine: "WS-0042",
          mac: null,
          source: "m365",
        },
      ],
    });
    expect(
      await screen.findByText(
        /^DHCP lease .*: WS-0042 \(MAC 00:00:5e:00:53:0a\) \(no end seen, assumed until/,
      ),
    ).toBeVisible();
    expect(screen.getByText(/^Company sign-in .*: bob@example.com on WS-0042$/)).toBeVisible();
    expect(String(spy.mock.calls[0]?.[0])).toContain(
      "/api/addresses/10.20.1.6?at=2026-10-10T11%3A00%3A00Z",
    );
  });

  it("shows nothing when nobody is known", async () => {
    const { view, spy } = renderWith({
      ip: "10.20.1.6",
      at: "x",
      max_age_hours: 24,
      holders: [],
      spans: [],
    });
    await vi.waitFor(() => expect(spy).toHaveBeenCalled());
    expect(view.container.textContent).toBe("");
  });
});
