import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

type Change = (url: string, body: Record<string, unknown>) => Record<string, unknown> | null;

/** The Dashboard, with `change` rewriting the JSON of the answers it wants to. */
async function renderDashboard(change: Change = () => null, auth?: MockAuth) {
  window.history.replaceState(null, "", "/dashboard");
  const spy = mockApi("Codename", auth ?? { mode: "login", signedIn: true, role: "admin" });
  const real = spy.getMockImplementation() as typeof fetch;
  spy.mockImplementation(async (url, init) => {
    const res = await real(url, init);
    if ((init?.method ?? "GET") !== "GET" || !res.ok) return res;
    const body = (await res.clone().json()) as Record<string, unknown>;
    const next = change(String(url), body);
    return next
      ? new Response(JSON.stringify(next), {
          status: 200,
          headers: { "content-type": "application/json" },
        })
      : res;
  });
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
  return spy;
}

const isDetections = (url: string) =>
  url.includes("/api/dashboard/sections") && url.includes("part=detections");

afterEach(() => vi.restoreAllMocks());

describe("Dashboard: Detections (ADR-0052, DESIGN.md 6.3, redesign build row 18)", () => {
  it("lists the hosts and people involved with their rules and last match", async () => {
    await renderDashboard();
    const section = await screen.findByRole("region", { name: "Detections" });
    for (const label of [
      "Matched events",
      "Rules that matched",
      "Hosts involved",
      "People involved",
    ])
      expect(section.querySelector(`[data-kpi="${label}"]`), label).not.toBeNull();
    const table = within(section).getByRole("table", { name: "Hosts and people involved" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["", "Name", "Rules", "Last match", "Matches"]);
    const row = within(table).getByRole("link", { name: "bastion" }).closest("tr") as HTMLElement;
    const cells = within(row).getAllByRole("cell");
    expect(cells[2]).toHaveTextContent(/^2$/);
    expect(cells[3]).toHaveTextContent("Oct 30, 9:58 AM"); // tests run in UTC
    expect(cells[4]).toHaveTextContent(/^9$/);
  });

  it("opens the rule from its name, and its events from its total", async () => {
    await renderDashboard();
    const section = await screen.findByRole("region", { name: "Detections" });
    const row = section.querySelector('tr[data-row="SSH failed password"]') as HTMLElement;
    // The total opens the events in Logs.
    expect(within(row).getByTitle("Open 9 events in Logs")).toHaveAttribute("data-drill");
    // The name opens Alerts > Rules, filtered to that rule.
    await userEvent.click(within(row).getByRole("button", { name: "SSH failed password" }));
    await waitFor(() => expect(window.location.pathname).toBe("/alerts/rules"));
    expect(new URLSearchParams(window.location.hash.slice(1)).get("rule")).toBe(
      "SSH failed password",
    );
    expect(
      await screen.findByPlaceholderText("Filter by title, author, tag, or log source"),
    ).toHaveValue("SSH failed password");
    // Editing the box drops the name from the address, so a reload keeps the edit.
    await userEvent.type(
      screen.getByPlaceholderText("Filter by title, author, tag, or log source"),
      "x",
    );
    expect(window.location.hash).toBe("");
  });

  it("says detection is not running, and never shows a zero for it", async () => {
    await renderDashboard((url, body) => {
      if (url.endsWith("/api/overview"))
        return {
          ...body,
          paused: [
            { schedule_id: "s9", name: "Failed logons", kind: "rule", reason: "The rule changed" },
            // Someone's own choice is not a blind state.
            { schedule_id: "s8", name: "Mine", kind: "search", reason: null, by_person: true },
            // A saved-search schedule the system paused is not detection.
            { schedule_id: "s7", name: "Failed SSH", kind: "search", reason: "The search changed" },
          ],
        };
      if (isDetections(url)) {
        const d = body.detections as Record<string, { value: number }>;
        return { ...body, detections: { ...d, hosts: { ...d.hosts, value: 0 } } };
      }
      return null;
    });
    const section = await screen.findByRole("region", { name: "Detections" });
    const notice = await within(section).findByRole("note");
    expect(notice).toHaveAttribute("data-state-notice", "blind");
    expect(notice).toHaveTextContent("Detection is not running for 1 schedule: Failed logons.");
    const hosts = section.querySelector('[data-kpi="Hosts involved"]') as HTMLElement;
    expect(within(hosts).getByText("Not running")).toBeVisible();
    expect(within(hosts).queryByText("0")).toBeNull();
    // A number that is not zero is still a real count.
    const matched = section.querySelector('[data-kpi="Matched events"]') as HTMLElement;
    expect(within(matched).getByText("20")).toBeVisible();
    expect(within(matched).queryByText("Not running")).toBeNull();
  });

  it("shows a zero as a zero while detection runs", async () => {
    await renderDashboard((url, body) => {
      if (url.endsWith("/api/overview")) return { ...body, paused: [] };
      if (!isDetections(url)) return null;
      const d = body.detections as Record<string, { value: number }>;
      return { ...body, detections: { ...d, hosts: { ...d.hosts, value: 0 } } };
    });
    const section = await screen.findByRole("region", { name: "Detections" });
    const hosts = section.querySelector('[data-kpi="Hosts involved"]') as HTMLElement;
    expect(within(hosts).getByText("0")).toBeVisible();
    expect(within(section).queryByRole("note")).toBeNull();
  });

  it("offers Enable rules to an administrator when no rule is enabled", async () => {
    await renderDashboard((url, body) =>
      isDetections(url) ? { ...body, detections: null, no_rules: true } : null,
    );
    const section = await screen.findByRole("region", { name: "Detections" });
    expect(within(section).getByText("No rules are enabled.")).toBeVisible();
    await userEvent.click(within(section).getByRole("button", { name: "Enable rules" }));
    expect(window.location.pathname).toBe("/alerts/rules");
  });

  it("shows nothing for it to someone who cannot enable a rule", async () => {
    await renderDashboard(
      (url, body) => (isDetections(url) ? { ...body, detections: null, no_rules: true } : null),
      { mode: "login", signedIn: true, role: "analyst" },
    );
    await screen.findByRole("region", { name: "Identity" });
    expect(screen.queryByRole("region", { name: "Detections" })).toBeNull();
    expect(screen.queryByText("No rules are enabled.")).toBeNull();
  });
});
