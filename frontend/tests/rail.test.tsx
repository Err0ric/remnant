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

/** The rail's entries by label (the current page's tab rows are not entries, D268). */
const entries = (nav: HTMLElement) => [...nav.querySelectorAll<HTMLElement>("[data-rail-entry]")];
const titles = (nav: HTMLElement) => entries(nav).map((a) => a.querySelector("span")?.textContent);

afterEach(() => window.history.replaceState(null, "", "/"));

describe("Rail (ADR-0052 section 3.2, redesign build row 4)", () => {
  it("has at most 10 entries in the model, and every one is a page", () => {
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
    const here = entries(nav).filter((a) => a.hasAttribute("aria-current"));
    expect(here.map((a) => a.dataset.railEntry)).toEqual(["alerts"]);
    // Alerts lists its tabs (D268): the entry is the current section, Queue the page.
    expect(here[0]).toHaveAttribute("aria-current", "true");
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

  it("shows no dot and no number beside Health when every source is healthy", async () => {
    const calm = await rail("/alerts", { mode: "login", signedIn: true, role: "admin" });
    await screen.findByRole("heading", { level: 1, name: "Alerts" });
    await new Promise((r) => setTimeout(r, 3000)); // past the rail's first read
    expect(calm.querySelector("[data-health-dot]")).toBeNull();
    expect(within(calm).getByRole("link", { name: "Health" })).toHaveTextContent(/^Health$/);
  });

  it("shows Health's status dot only, no number, its words naming the state and count (item 7)", async () => {
    const nav = await rail("/alerts", {
      mode: "login",
      signedIn: true,
      role: "admin",
      healthCount: { total: 5, not_healthy: 2, unhealthy: 0 },
    });
    const health = await within(nav).findByRole(
      "link",
      { name: "Health: 2 sources need attention" },
      { timeout: 5000 },
    );
    const dot = within(health).getByRole("img", { name: "Health: 2 sources need attention" });
    // One tooltip per entry (D268): the state leads Health's own, the dot has none.
    expect(dot).not.toHaveAttribute("title");
    expect(health.parentElement!.querySelector('[role="tooltip"]')).toHaveTextContent(
      "Health: 2 sources need attention. Whether every source and collector is sending",
    );
    expect(dot).toHaveAttribute("data-health-dot", "attention");
    expect(dot).toHaveClass("bg-warn");
    expect(health).toHaveTextContent(/^Health$/); // no number
  });

  it("colors the Health dot by the worst state: unhealthy in the danger color", async () => {
    const nav = await rail("/alerts", {
      mode: "login",
      signedIn: true,
      role: "admin",
      healthCount: { total: 5, not_healthy: 3, unhealthy: 1 },
    });
    const health = await within(nav).findByRole(
      "link",
      { name: "Health: 3 sources need attention, 1 unhealthy" },
      { timeout: 5000 },
    );
    const dot = health.querySelector("[data-health-dot]");
    expect(dot).toHaveAttribute("data-health-dot", "unhealthy");
    expect(dot).toHaveClass("bg-danger");
  });

  it("puts every count that asks for action on the solid High pair: Alerts and AI usage alike", async () => {
    const nav = await rail("/dashboard", {
      mode: "login",
      signedIn: true,
      role: "admin",
      aiToReview: 3,
    });
    const alerts = within(nav).getByRole("link", { name: /^Alerts/ });
    const open = await within(alerts).findByLabelText(/open$/);
    const ai = within(nav).getByRole("link", { name: /^AI usage/ });
    const review = await within(ai).findByLabelText("3 to review", {}, { timeout: 5000 });
    expect(open.className).toBe(review.className);
    expect(review).toHaveClass("bg-sev-h-solid", "text-sev-h-on");
  });

  it("reads the Health dot from what the page already loaded, without a second request", async () => {
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
    // And the dot says what that Overview says, by the server's rule.
    const { sourceProblems, healthWords } = await import("@/features/health/flow");
    const { api } = await import("@/lib/api");
    const words = healthWords(sourceProblems(await api.overview()));
    expect(words).not.toBe("");
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: words })).toBeInTheDocument();
  });

  it("counts only the server's source problems: never a paused or held source", async () => {
    const { sourceProblems } = await import("@/features/health/flow");
    const o = (problems: (string | null)[]) =>
      ({ sources: problems.map((problem, i) => ({ source_id: `s${i}`, problem })) }) as never;
    expect(sourceProblems(o([null, null, null]))).toEqual({ count: 0, unhealthy: 0, damaged: 0 });
    expect(sourceProblems(o([null, "attention", "unhealthy", "attention"]))).toEqual({
      count: 3,
      unhealthy: 1,
      damaged: 0,
    });
    expect(sourceProblems(undefined)).toEqual({ count: 0, unhealthy: 0, damaged: 0 });
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
