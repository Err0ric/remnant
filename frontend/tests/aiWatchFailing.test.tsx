import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, mockFlags, type MockAuth } from "./mockApi";

async function renderAt(path: string, auth: MockAuth) {
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

afterEach(() => {
  mockFlags.aiWatchFailing = false;
  vi.restoreAllMocks();
});

const ADMIN: MockAuth = { mode: "login", signedIn: true, role: "admin" };

describe("Failing AI Watch checks are on screen (owner, 2026-11-03)", () => {
  it("the Dashboard's AI Watch panel says since when, how often, and why", async () => {
    mockFlags.aiWatchFailing = true;
    await renderAt("/", ADMIN);
    const panel = await screen.findByRole("region", { name: "AI Watch" });
    const alert = await within(panel).findByRole("alert");
    expect(alert).toHaveTextContent("AI Watch checks are failing since");
    expect(alert).toHaveTextContent("the hourly review (4x)");
    expect(alert).toHaveTextContent("Could not convert string [values not logged]");
  });

  it("an analyst sees that checks fail, not why", async () => {
    mockFlags.aiWatchFailing = true;
    await renderAt("/", { mode: "login", signedIn: true, role: "analyst" });
    const panel = await screen.findByRole("region", { name: "AI Watch" });
    const alert = await within(panel).findByRole("alert");
    expect(alert).toHaveTextContent("An administrator can see why on Health.");
    expect(alert).not.toHaveTextContent("ConversionException");
  });

  it("Health lists failing checks and Check AI Watch now shows each step", async () => {
    mockFlags.aiWatchFailing = true;
    const spy = await renderAt("/health", ADMIN);
    const section = await screen.findByRole("region", { name: "Background checks failing" });
    expect(within(section).getByText("AI Watch: hourly review")).toBeVisible();
    expect(within(section).getByText("4")).toBeVisible();
    await userEvent.click(within(section).getByRole("button", { name: "Check AI Watch now" }));
    const steps = await within(section).findByRole("list", { name: "AI Watch check" });
    expect(within(steps).getByText("AI Watch: new AI use: worked")).toBeVisible();
    expect(within(steps).getByText(/AI Watch: hourly review: ConversionException/)).toBeVisible();
    expect(
      spy.mock.calls.some(
        ([u, i]) => String(u).endsWith("/api/ai/watch/check") && i?.method === "POST",
      ),
    ).toBe(true);
  });

  it("nothing shows while the checks work", async () => {
    await renderAt("/health", ADMIN);
    await screen.findByRole("heading", { name: "Health", level: 1 });
    expect(screen.queryByRole("region", { name: "Background checks failing" })).toBeNull();
  });
});
