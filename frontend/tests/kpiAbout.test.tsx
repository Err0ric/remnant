import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

/** Owner 2026-11-02: every number on these pages says how it is counted. Fails when a new
 * KPI or tile ships without its (i). */
async function renderAt(path: string) {
  window.history.replaceState(null, "", path);
  mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  render(
    <App
      initialTheme="dark"
      queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    />,
  );
}

afterEach(() => vi.restoreAllMocks());

function kpis(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>("[data-kpi]"));
}

describe.each([
  ["Dashboard", "/dashboard", 10],
  ["Microsoft 365", "/m365", 7],
  ["Agents overview", "/agents", 6],
  ["Health", "/health", 4],
])("How this is counted on %s", (_name, path, least) => {
  it("puts an (i) with its counting rule on every number", async () => {
    await renderAt(path);
    await waitFor(() => expect(kpis().length).toBeGreaterThanOrEqual(least));
    for (const k of kpis()) {
      const about = k.querySelector("[data-about]");
      expect(about, `${k.dataset.kpi} has no "How this is counted"`).not.toBeNull();
      expect(about?.getAttribute("aria-label") ?? "").toMatch(/^How this is counted: .{40,}/);
    }
  });
});

describe("The specific ones the owner named", () => {
  it("spells out external, attacking addresses, countries, and unapproved AI people", async () => {
    const { COUNTED, AI_WATCH_COUNTED } = await import("@/features/dashboard/counted");
    expect(COUNTED.externalFailures).toMatch(/SSH.*Windows.*VPN/);
    expect(COUNTED.externalFailures).toMatch(/not in your internal networks/);
    expect(COUNTED.attackingAddresses).toMatch(/at least one failed login/);
    expect(COUNTED.countries).toMatch(/GeoIP/);
    expect(AI_WATCH_COUNTED.people).toMatch(/not yet approved \(Not approved or Unreviewed/);
    expect(AI_WATCH_COUNTED.people).toMatch(/Devices no person maps to are counted apart/);
    expect(screen).toBeDefined();
  });
});
