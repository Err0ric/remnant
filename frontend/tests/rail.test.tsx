import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AREAS, RAIL_GROUPS } from "@/lib/nav";
import { mockApi, type MockAuth } from "./mockApi";

async function rail(path: string, auth: MockAuth) {
  window.history.replaceState(null, "", path);
  mockApi("Codename", auth);
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
  return screen.findByRole("navigation", { name: "Primary" });
}

const titles = (nav: HTMLElement) =>
  within(nav)
    .getAllByRole("link")
    .map((a) => a.getAttribute("title"));

afterEach(() => window.history.replaceState(null, "", "/"));

describe("Rail (ADR-0052 section 3.2, redesign build row 4)", () => {
  it("has at most 10 entries in the model, and every one is a page with no children", () => {
    const ids = RAIL_GROUPS.flatMap((g) => g.areas);
    expect(ids.length + 1).toBeLessThanOrEqual(10); // plus Settings
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(AREAS.some((a) => a.id === id)).toBe(true);
    // Microsoft 365 is no area: its lists are views of Logs (ADR-0052 section 3.3).
    expect(AREAS.some((a) => a.id === "m365")).toBe(false);
    const logs = AREAS.find((a) => a.id === "logs");
    expect(logs?.tabs.filter((t) => t.view).map((t) => t.tab)).toEqual([
      "sign-ins",
      "mail",
      "admin",
    ]);
  });

  it("shows an Analyst the daily pages, with Settings limited to what they can open", async () => {
    const nav = await rail("/alerts", { mode: "login", signedIn: true, role: "analyst" });
    expect(titles(nav)).toEqual([
      "Dashboard",
      "Alerts",
      "Logs",
      "Ask AI",
      "People & devices",
      "AI usage",
      "Agents",
      "Health",
      "Settings",
    ]);
    const here = within(nav)
      .getAllByRole("link")
      .filter((a) => a.hasAttribute("aria-current"));
    expect(here.map((a) => a.getAttribute("title"))).toEqual(["Alerts"]);
    expect(here[0]).toHaveAttribute("aria-current", "page");
  });

  it("shows an Auditor only what they can open: no Ask AI, and Logs opens Saved searches", async () => {
    const nav = await rail("/alerts", { mode: "login", signedIn: true, role: "auditor" });
    expect(titles(nav)).not.toContain("Ask AI");
    expect(within(nav).getByRole("link", { name: "Logs" })).toHaveAttribute(
      "href",
      "/investigate/saved",
    );
    expect(titles(nav)).toContain("Settings"); // the audit log lives there
  });

  it("gives an Auditor the search again when an administrator allows Auditor SQL", async () => {
    const nav = await rail("/alerts", {
      mode: "login",
      signedIn: true,
      role: "auditor",
      auditorSql: true,
    });
    // The setting is read after the page opens.
    await waitFor(() =>
      expect(within(nav).getByRole("link", { name: "Logs" })).toHaveAttribute(
        "href",
        "/investigate/logs",
      ),
    );
  });

  it("shows no count beside Health when every source is healthy", async () => {
    const calm = await rail("/alerts", { mode: "login", signedIn: true, role: "admin" });
    await screen.findByRole("heading", { level: 1, name: "Alerts" });
    await new Promise((r) => setTimeout(r, 3000)); // past the rail's first read
    expect(calm.querySelector("[data-health-count]")).toBeNull();
    expect(calm.querySelector("[data-health-dot]")).toBeNull();
  });

  it("says how many sources need attention beside Health, outlined in warn, in place of the dot", async () => {
    const nav = await rail("/alerts", {
      mode: "login",
      signedIn: true,
      role: "admin",
      healthCount: { total: 5, not_healthy: 2 },
    });
    const health = within(nav).getByRole("link", { name: /^Health/ });
    expect(await within(health).findByText("2 sources need attention")).toHaveClass("sr-only");
    const count = health.querySelector("[data-health-count]");
    expect(count).toHaveClass("border", "border-warn", "text-warn");
    expect(count).toHaveAttribute("title", "2 sources need attention");
    expect(count?.querySelector("[aria-hidden]")).toHaveTextContent(/^2$/);
    expect(health.querySelector("[data-health-dot]")).toBeNull();
  });

  it("puts the open alert count on the solid High pair", async () => {
    const nav = await rail("/dashboard", { mode: "login", signedIn: true, role: "admin" });
    const alerts = within(nav).getByRole("link", { name: /^Alerts/ });
    const count = await within(alerts).findByLabelText(/open$/);
    expect(count).toHaveClass("bg-sev-h-solid", "text-sev-h-on");
  });

  it("reads the Health count from what the page already loaded, without a second request", async () => {
    window.history.replaceState(null, "", "/health");
    const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
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
    await screen.findByRole("heading", { level: 1, name: "Health" });
    // Past the rail's first read: the Overview the Health page loaded answered it.
    await new Promise((r) => setTimeout(r, 3000));
    const asked = spy.mock.calls.map(([u]) => String(u));
    expect(asked.some((u) => u.endsWith("/api/overview"))).toBe(true);
    expect(asked.some((u) => u.endsWith("/api/health/count"))).toBe(false);
    // And the dot says what that Overview says, by the same rule as the server's count.
    const { needingAttention } = await import("@/features/health/flow");
    const { api } = await import("@/lib/api");
    const n = needingAttention(await api.overview());
    const health = within(screen.getByRole("navigation", { name: "Primary" })).getByRole("link", {
      name: /^Health/,
    });
    if (n) expect(within(health).getByText(/need(s)? attention$/)).toHaveTextContent(`${n} `);
    else expect(health.querySelector("[data-health-count]")).toBeNull();
  });

  it("does not count a source paused on purpose, as the server's count does not", async () => {
    const { needingAttention } = await import("@/features/health/flow");
    const o = (conditions: string[]) =>
      ({ sources: conditions.map((condition, i) => ({ source_id: `s${i}`, condition })) }) as never;
    expect(needingAttention(o(["healthy", "paused", "paused"]))).toBe(0);
    expect(needingAttention(o(["healthy", "paused", "quiet", "error", "gap", "attention"]))).toBe(
      4,
    );
    expect(needingAttention(undefined)).toBe(0);
  });

  it("lists Logs in Ctrl+K only for those who may search, and its Saved searches tab for all", async () => {
    await rail("/alerts", { mode: "login", signedIn: true, role: "auditor" });
    await userEvent.keyboard("{Control>}k{/Control}");
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByRole("combobox"), "logs");
    const labels = (await within(dialog).findAllByRole("option")).map((o) => o.textContent ?? "");
    expect(labels.some((l) => l.startsWith("Logs › Saved searches"))).toBe(true);
    expect(labels.some((l) => /^Logs(?! ›)/.test(l))).toBe(false);
  });

  it("gives an Auditor without SQL no Search tab in the Logs header", async () => {
    await rail("/investigate/saved", { mode: "login", signedIn: true, role: "auditor" });
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Saved searches");
    expect(screen.queryByRole("navigation", { name: "Logs tabs" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Search" })).toBeNull();
  });
});
