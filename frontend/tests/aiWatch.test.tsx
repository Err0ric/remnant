import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, type MockAuth } from "./mockApi";

async function renderAt(
  path: string,
  auth: MockAuth = { mode: "login", signedIn: true, role: "admin" },
) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", auth);
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

describe("AI Watch on the Dashboard (ADR-0035 Part 2)", () => {
  it("shows five cards against the previous period, the 30-day chart, and top services", async () => {
    const spy = await renderAt("/dashboard");
    const watch = await screen.findByRole("region", { name: "AI Watch" });
    expect(within(watch).getByText("Unapproved AI services")).toBeVisible();
    expect(within(watch).getByRole("button", { name: "2" })).toBeVisible();
    expect(within(watch).getAllByText("+1 vs previous 7 days")).toHaveLength(2);
    expect(within(watch).getByText("same as previous 7 days")).toBeVisible();
    // People and devices are never one number: devices without a person are their own line.
    expect(
      within(watch).getByRole("button", { name: "2 more devices not matched to a person" }),
    ).toBeVisible();
    // A card without its source takes no card (F62): one muted line with the setup link.
    expect(within(watch).queryByText("App consent grants")).toBeNull();
    expect(within(watch).getByText(/^Not set up:/)).toHaveTextContent(
      "app consent grants (needs a Microsoft 365 source)",
    );
    expect(within(watch).getByRole("button", { name: "Add a source" })).toBeVisible();
    expect(within(watch).getByText("Restricted")).toBeVisible();
    // New in 24 hours sits under the cards, from first seen.
    expect(within(watch).getByRole("link", { name: "DeepSeek (AI service)" })).toHaveAttribute(
      "href",
      "/alerts#item=w1",
    );
    expect(
      within(watch).getByRole("img", { name: /^AI use per day over 30 days by review status:/ }),
    ).toBeVisible();
    const top = within(watch).getByRole("table", { name: "Top AI services" });
    expect(within(top).getByRole("link", { name: "DeepSeek" })).toBeVisible();
    expect(within(top).getByText("Not approved")).toBeVisible();
    await userEvent.click(within(watch).getByRole("button", { name: "30 days" }));
    await vi.waitFor(() =>
      expect(
        spy.mock.calls.some(([u]) => String(u).endsWith("/api/ai/watch/summary?days=30")),
      ).toBe(true),
    );
  });
});
