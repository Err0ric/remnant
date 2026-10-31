import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

async function renderAt(path: string) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
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

describe("Microsoft 365 area (ADR-0038 section 5)", () => {
  it("sits under Monitor and shows the Overview with every number openable", async () => {
    await renderAt("/m365");
    const overview = await screen.findByRole("region", { name: "Overview" });
    const monitor = screen.getByRole("region", { name: "Monitor" });
    expect(within(monitor).getAllByText("Microsoft 365")[0]).toBeVisible();
    expect(screen.getByRole("navigation", { name: "Microsoft 365 tabs" })).toBeVisible();
    for (const card of document.querySelectorAll<HTMLElement>("[data-kpi]")) {
      if (/not set|Set approved countries/i.test(card.textContent ?? "")) continue;
      expect(card.querySelector("[data-drill]"), card.dataset.kpi).not.toBeNull();
    }
    const outcomes = screen.getByRole("region", { name: "Sign-in outcomes" });
    expect(within(outcomes).getByRole("img", { name: /12 failed/ })).toHaveAttribute("data-drill");
    expect(within(overview).getByTitle("Open 31 events in Search")).toBeVisible();
    await userEvent.click(within(overview).getByTitle("Open 12 events in Search"));
    await waitFor(() => expect(window.location.pathname).toBe("/investigate/search"));
    expect(
      await screen.findByText(/^From Microsoft 365 > Overview > Failed sign-ins, Oct 24/),
    ).toBeVisible();
  });

  it("lists a tab's events over the page window", async () => {
    const spy = await renderAt("/m365/sign-ins");
    await screen.findByRole("region", { name: "Sign-ins" });
    await waitFor(() => {
      const bodies = spy.mock.calls
        .filter(([u, i]) => String(u).endsWith("/api/query") && i?.method === "POST")
        .map(([, i]) => JSON.parse(String(i?.body)) as { sql: string; start?: string });
      expect(bodies.some((b) => b.sql.includes("2026-10-24T00:00:00+00:00") && b.start)).toBe(true);
    });
  });
});
