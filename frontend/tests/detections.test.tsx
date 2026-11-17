import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth, loadedRegion, withM365 } from "./mockApi";

type Change = (url: string, body: Record<string, unknown>) => Record<string, unknown> | null;

/** The Dashboard, with `change` rewriting the JSON of the answers it wants to. */
async function renderDashboard(change: Change = () => null, auth?: MockAuth) {
  window.history.replaceState(null, "", "/dashboard");
  const spy = withM365(
    mockApi("Codename", auth ?? { mode: "login", signedIn: true, role: "admin" }),
  );
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

const isOverview = (url: string) => /\/api\/overview$/.test(url);
const asked = (spy: ReturnType<typeof mockApi>, test: (url: string) => boolean) =>
  spy.mock.calls.some((c) => test(String(c[0])));

const isDetections = (url: string) =>
  url.includes("/api/dashboard/sections") && url.includes("part=detections");

afterEach(() => vi.restoreAllMocks());

describe("Dashboard: Detections (ADR-0052, DESIGN.md 6.3, redesign build row 18)", () => {
  it("lists the hosts and people involved with their rules and last match", async () => {
    await renderDashboard();
    const section = await loadedRegion("Detections");
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
    const section = await loadedRegion("Detections");
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
    const section = await loadedRegion("Detections");
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
    const section = await loadedRegion("Detections");
    const hosts = section.querySelector('[data-kpi="Hosts involved"]') as HTMLElement;
    expect(within(hosts).getByText("0")).toBeVisible();
    expect(within(section).queryByRole("note")).toBeNull();
  });

  it("offers Enable rules to an administrator when no rule is enabled", async () => {
    await renderDashboard((url, body) =>
      isDetections(url) ? { ...body, detections: null, no_rules: true } : null,
    );
    const section = await loadedRegion("Detections");
    expect(within(section).getByText("No rules are enabled.")).toBeVisible();
    await userEvent.click(within(section).getByRole("button", { name: "Enable rules" }));
    expect(window.location.pathname).toBe("/alerts/rules");
  });

  it("hides Detections from someone who cannot enable a rule, from the first paint", async () => {
    // The Overview says no rule is on and no match is kept: nothing for them to act on, so
    // the section is not drawn (as before item 27), and its answer is never asked for.
    const spy = await renderDashboard(
      (url, body) =>
        isOverview(url) ? { ...body, rules_enabled: 0, rules_last_match: null } : null,
      { mode: "login", signedIn: true, role: "analyst" },
    );
    await loadedRegion("Identity");
    expect(screen.queryByRole("region", { name: "Detections" })).toBeNull();
    expect(screen.queryByText("No rules are enabled.")).toBeNull();
    expect(asked(spy, isDetections)).toBe(false);
  });

  it("draws no rule enabled at once from the Overview, without asking for the section", async () => {
    const spy = await renderDashboard((url, body) =>
      isOverview(url) ? { ...body, rules_enabled: 0, rules_last_match: null } : null,
    );
    const section = await screen.findByRole("region", { name: "Detections" });
    expect(within(section).getByText("No rules are enabled.")).toBeVisible();
    expect(within(section).getByRole("button", { name: "Enable rules" })).toBeVisible();
    // Its own height, no box and no skeleton cards.
    expect(section.closest("[data-slot]")).toBeNull();
    expect(section.querySelector("[data-kpi]")).toBeNull();
    expect(asked(spy, isDetections)).toBe(false);
  });

  it("still shows matches kept from before the rules were turned off (code review)", async () => {
    // No rule on, but a match since the window before: the section loads as on main.
    const recent = new Date(Date.now() - 3_600_000).toISOString();
    const spy = await renderDashboard((url, body) =>
      isOverview(url) ? { ...body, rules_enabled: 0, rules_last_match: recent } : null,
    );
    const section = await loadedRegion("Detections");
    expect(section.querySelector('[data-kpi="Matched events"]')).not.toBeNull();
    expect(screen.queryByText("No rules are enabled.")).toBeNull();
    expect(asked(spy, isDetections)).toBe(true);
  });

  it("draws the egress note in Attacks and access while its numbers load", async () => {
    // The Overview says no company egress is listed; the sections are held back.
    const held = new Promise<Response>(() => undefined);
    const spy = withM365(mockApi("Codename", { mode: "login", signedIn: true, role: "admin" }));
    const real = spy.getMockImplementation() as typeof fetch;
    spy.mockImplementation(async (url, init) => {
      if (String(url).includes("/api/dashboard/sections")) return held;
      const res = await real(url, init);
      if (!isOverview(String(url))) return res;
      const body = (await res.clone().json()) as { sources: Record<string, unknown>[] };
      // Its sources sent events just now, so Attacks and access is not known to be empty.
      const now = new Date().toISOString();
      const sources = body.sources.map((h) => ({ ...h, newest_event_at: now, last_event_at: now }));
      return new Response(JSON.stringify({ ...body, sources, egress_listed: false }), {
        headers: { "content-type": "application/json" },
      });
    });
    window.history.replaceState(null, "", "/dashboard");
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    render(<App initialTheme="dark" queryClient={new QueryClient()} />);
    const attacks = await screen.findByRole("region", { name: "Attacks and access" });
    expect(within(attacks).getByText(/^Company egress addresses are not listed/)).toBeVisible();
    expect(within(attacks).getAllByRole("status", { name: /^Loading / }).length).toBeGreaterThan(0);
  });

  it("keeps every section when the sources answer fails, with Retry for it (code review)", async () => {
    const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
    const real = spy.getMockImplementation() as typeof fetch;
    spy.mockImplementation(async (url, init) =>
      String(url).endsWith("/api/sources") && (init?.method ?? "GET") === "GET"
        ? new Response(JSON.stringify({ error: { code: "internal", message: "It broke" } }), {
            status: 500,
            headers: { "content-type": "application/json" },
          })
        : real(url, init),
    );
    window.history.replaceState(null, "", "/dashboard");
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);
    // Each part is drawn and loads on its own, as before item 27.
    for (const name of ["Identity", "Attacks and access", "Detections"])
      expect(await loadedRegion(name)).toBeVisible();
    expect(screen.getByRole("region", { name: "Key numbers" })).toHaveAttribute("data-tiles", "5");
    const failed = screen.getByText(/^Your sources did not load/);
    expect(failed.closest("[role=alert]") ?? failed).toBeVisible();
    expect(screen.getAllByRole("button", { name: "Retry" }).length).toBeGreaterThan(0);
  });
});
