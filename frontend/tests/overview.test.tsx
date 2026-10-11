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

describe("Overview", () => {
  it("is the landing page and shows volume, ingest health, detections, and pauses", async () => {
    await renderAt("/");
    expect(await screen.findByRole("heading", { name: "Overview", level: 1 })).toBeVisible();
    const volume = await screen.findByRole("region", { name: "Event volume" });
    expect(within(volume).getByText("88 events · last 24 hours")).toBeVisible();
    const rows = within(volume).getAllByRole("row");
    expect(within(rows[1]!).getByText("linux_sshd")).toBeVisible(); // busiest first
    expect(within(volume).getByRole("img", { name: /^win_dc: 40 events/ })).toBeVisible();
    const ingest = screen.getByRole("region", { name: "Ingest health" });
    expect(within(ingest).getByText("1 with errors")).toBeVisible();
    expect(within(ingest).getByText("Received 4 min ago")).toBeVisible();
    expect(within(ingest).getByText("Nothing received in 7 days")).toBeVisible();
    const paused = screen.getByRole("region", { name: "Paused schedules" });
    expect(within(paused).getByText(/saved search changed/)).toBeVisible();
    const nav = screen.getByRole("navigation");
    expect(within(nav).getByRole("link", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("opens a rule detection's matches in Search", async () => {
    await renderAt("/overview");
    const detections = await screen.findByRole("region", { name: "Detections" });
    await userEvent.click(within(detections).getByRole("button", { name: "Failed logon" }));
    expect(await screen.findByRole("heading", { name: "Search", level: 1 })).toBeVisible();
    expect(window.location.pathname).toBe("/search");
  });

  it("shows alert delivery to admins only", async () => {
    await renderAt("/overview");
    const alerts = await screen.findByRole("region", { name: "Alert delivery" });
    expect(within(alerts).getByText("Failing")).toBeVisible();
    expect(within(alerts).getByText("2 deliveries failed after every retry")).toBeVisible();
  });

  it("hides alert delivery from analysts", async () => {
    await renderAt("/overview", { mode: "login", signedIn: true, role: "analyst" });
    await screen.findByRole("region", { name: "Detections" });
    expect(screen.queryByRole("region", { name: "Alert delivery" })).toBeNull();
  });

  it("goes home from the product mark", async () => {
    await renderAt("/schedules");
    await userEvent.click(await screen.findByRole("link", { name: "Codename overview" }));
    expect(await screen.findByRole("heading", { name: "Overview", level: 1 })).toBeVisible();
  });
});
