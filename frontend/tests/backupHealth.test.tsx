import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, mockFlags, type MockAuth } from "./mockApi";

async function renderAt(path: string, role: MockAuth["role"] = "admin") {
  window.history.replaceState(null, "", path);
  mockApi("Codename", { mode: "login", signedIn: true, role });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
}

afterEach(() => vi.restoreAllMocks());

describe("Scheduled backups (handoff item 8)", () => {
  it("Health shows the last backup plainly when it failed, in local time with UTC on hover", async () => {
    await renderAt("/health");
    await userEvent.click(
      within(await screen.findByRole("navigation", { name: "Health tabs" })).getByRole("link", {
        name: /Backups/,
      }),
    );
    const table = await screen.findByRole("table", { name: "Backups" });
    expect(within(table).getByText("Scheduled backup")).toBeVisible();
    expect(
      within(table).getByText("The last backup failed: OSError: read-only file system"),
    ).toBeVisible();
    const detail = within(table).getByText(/Last run Oct 10, 2:15 AM · Failed · 3 on disk/);
    expect(detail).toHaveAttribute("title", "2026-10-10 02:15 UTC");
    expect(within(table).getAllByText("Unhealthy").length).toBeGreaterThan(0);
  });

  it("an administrator changes the time and count in Settings", async () => {
    mockFlags.backupPuts = 0;
    await renderAt("/about");
    const section = await screen.findByRole("region", { name: "Backups" });
    const keep = await within(section).findByLabelText("Backups kept");
    await userEvent.clear(keep);
    await userEvent.type(keep, "7");
    await userEvent.click(within(section).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(mockFlags.backupPuts).toBe(1));
  });

  it("is not shown to an analyst", async () => {
    await renderAt("/about", "analyst");
    expect(
      await screen.findByRole("heading", { name: "About and licenses", level: 1 }),
    ).toBeVisible();
    expect(screen.queryByRole("region", { name: "Backups" })).toBeNull();
  });
});
