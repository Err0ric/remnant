import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

const ADMIN: MockAuth = { mode: "login", signedIn: true, role: "admin" };

afterEach(() => {
  vi.restoreAllMocks();
});

describe("The alert badge reads a count only (D242)", () => {
  it("shows the open alerts without fetching the alert list", async () => {
    window.history.replaceState(null, "", "/logs");
    const spy = mockApi("Codename", ADMIN);
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(<App initialTheme="dark" queryClient={client} />);
    expect((await screen.findAllByLabelText(/^\d+ open$/)).length).toBeGreaterThan(0);
    const urls = spy.mock.calls.map(([u]) => String(u));
    expect(urls.some((u) => u.endsWith("/api/alerts/count"))).toBe(true);
    expect(urls.some((u) => u.includes("/api/alerts?"))).toBe(false);
  });

  it("the Dashboard banner reads only the lines it shows, not the alert list", async () => {
    window.history.replaceState(null, "", "/dashboard");
    const spy = mockApi("Codename", ADMIN);
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(<App initialTheme="dark" queryClient={client} />);
    expect(await screen.findByRole("region", { name: "Needs you" })).toBeTruthy();
    const urls = spy.mock.calls.map(([u]) => String(u));
    expect(urls.some((u) => u.includes("/api/alerts/lines?limit=5&by=severity"))).toBe(true);
    expect(urls.some((u) => u.includes("/api/alerts?"))).toBe(false);
  });
});
