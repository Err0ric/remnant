import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

async function renderDashboard() {
  window.history.replaceState(null, "", "/dashboard");
  window.localStorage.removeItem("dashboard.window");
  mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
  await screen.findByRole("region", { name: "Identity" });
}

afterEach(() => vi.restoreAllMocks());

const SECTIONS = ["Identity", "Attacks and access", "Detections"];

describe("Dashboard drill-through (ADR-0039)", () => {
  it("gives every KPI, chart, and table row a target", async () => {
    await renderDashboard();
    for (const name of SECTIONS) {
      const region = screen.getByRole("region", { name });
      const cards = region.querySelectorAll<HTMLElement>("[data-kpi]");
      expect(cards.length, name).toBeGreaterThan(0);
      for (const card of cards) {
        // A card waiting on a setting ("Set approved countries") has no number to open.
        const needs =
          card.querySelector("button:not([data-drill])") && !card.querySelector("[data-drill]");
        if (needs || /Needs a GeoIP file|No VPN logs|not set/i.test(card.textContent ?? ""))
          continue;
        expect(card.querySelector("[data-drill]"), `${name} > ${card.dataset.kpi}`).not.toBeNull();
      }
      for (const chart of region.querySelectorAll<HTMLElement>("[role=img][tabindex='0']"))
        expect(chart.hasAttribute("data-drill"), `${name} chart`).toBe(true);
      for (const row of region.querySelectorAll<HTMLElement>("tr[data-row]"))
        expect(
          row.querySelector("[data-drill], a[href]"),
          `${name} row ${row.dataset.row}`,
        ).not.toBeNull();
    }
  });

  it("opens the card's rows in Search, labelled, and Back returns to the Dashboard", async () => {
    await renderDashboard();
    const identity = screen.getByRole("region", { name: "Identity" });
    const failed = within(identity).getByRole("button", {
      name: "Failed sign-ins: 12. Open events in Search",
    });
    expect(failed).toHaveAttribute("title", "Open 12 events in Search");
    await userEvent.click(failed);
    await waitFor(() => expect(window.location.pathname).toBe("/investigate/search"));
    expect(
      await screen.findByText(/^From Dashboard > Identity > Failed sign-ins, Oct 24, 12:00 AM to/),
    ).toBeVisible();
    window.history.back();
    await screen.findByRole("region", { name: "Identity" });
    expect(window.location.pathname).toBe("/dashboard");
  });

  it("opens the window before from the change pill", async () => {
    await renderDashboard();
    const attacks = screen.getByRole("region", { name: "Detections" });
    const pill = within(attacks).getAllByTitle(/from the previous 7 days in Search$/)[0];
    await userEvent.click(pill as HTMLElement);
    await waitFor(() => expect(window.location.pathname).toBe("/investigate/search"));
    expect(
      await screen.findByText(
        /^From Dashboard > Detections > Rule matches \(the previous 7 days\), Oct 17/,
      ),
    ).toBeVisible();
  });
});
