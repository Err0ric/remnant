import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

afterEach(() => vi.restoreAllMocks());

describe("People and devices while it loads (review item 7)", () => {
  it("shows progress and no made-up counts until the ranking arrives", async () => {
    window.history.replaceState(null, "", "/investigations");
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    spy.mockImplementation(async (input, init) => {
      if (String(input).includes("/api/entities/risk")) await held;
      return base(input, init);
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);

    const tabs = await screen.findByRole("tablist", { name: "Entity type" });
    const labels = () =>
      within(tabs)
        .getAllByRole("tab")
        .map((t) => t.textContent);
    expect(labels()).toEqual(["Users", "IP addresses", "Hosts", "Targeted usernames"]);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveTextContent(/Counting people and devices/);
    expect(screen.queryByText(/\(0\)/)).toBeNull();

    release();
    expect(await within(tabs).findByRole("tab", { name: "Users (4)" })).toBeVisible();
    expect(labels()).toEqual([
      "Users (4)",
      "IP addresses (1)",
      "Hosts (1)",
      "Targeted usernames (2)",
    ]);
    expect(screen.queryByRole("status")).toBeNull();
  });
});
