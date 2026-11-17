import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi, type MockAuth, loadedRegion, withM365 } from "./mockApi";

async function renderAt(
  path: string,
  auth: MockAuth = { mode: "login", signedIn: true, role: "admin" },
  tweak?: (spy: ReturnType<typeof mockApi>) => void,
) {
  window.history.replaceState(null, "", path);
  const spy = withM365(mockApi("Codename", auth));
  tweak?.(spy);
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
  it("counts granted consents, shows blocked ones apart, and opens each card's rows (F66)", async () => {
    const consent = {
      key: "consent",
      label: "App consent grants",
      value: 1,
      previous: 0,
      context: "Latest: Lab Notes App (User.Read, Mail.Read) by admin@example.com",
      needs: null,
      restricted: false,
      blocked: 2,
      blocked_context: "Blocked: Lab Notes Beta (openid, profile) by erin@example.com",
      drill: "SELECT 'granted' AS which WHERE TIMESTAMPTZ '{from}' < TIMESTAMPTZ '{to}'",
      blocked_drill: "SELECT 'blocked' AS which WHERE TIMESTAMPTZ '{from}' < TIMESTAMPTZ '{to}'",
    };
    window.history.replaceState(null, "", "/dashboard");
    const spy = withM365(mockApi("Codename", { mode: "login", signedIn: true, role: "admin" }));
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) => {
      const res = await base(input, init);
      if (!String(input).includes("/api/ai/watch/summary")) return res;
      const body = await res.json();
      body.cards = body.cards.map((c: { key: string }) => (c.key === "consent" ? consent : c));
      body.people_pending_days = 3;
      body.people_days = 30;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(<App initialTheme="dark" queryClient={client} />);
    const watch = await loadedRegion("AI Watch");
    expect(within(watch).getByText("App consent grants")).toBeVisible();
    expect(within(watch).getByText(/^Latest: Lab Notes App/)).toBeVisible();
    expect(within(watch).getByText(/^Blocked: Lab Notes Beta/)).toBeVisible();
    // Older days still being re-checked: said, never a failure (owner, 2026-10-29).
    expect(within(watch).getByRole("status")).toHaveTextContent(
      "Rebuilding people for 3 of 30 days",
    );
    await userEvent.click(
      within(watch).getByRole("button", { name: "2 blocked consent attempts" }),
    );
    await vi.waitFor(() => expect(window.location.pathname).toBe("/investigate/logs"));
    await vi.waitFor(() =>
      expect(
        spy.mock.calls.some(
          ([u, init]) =>
            String(u).endsWith("/api/query") &&
            String(init?.body).includes("SELECT 'blocked' AS which"),
        ),
      ).toBe(true),
    );
  });

  it("shows five cards against the previous period, the 30-day chart, and top services", async () => {
    const spy = await renderAt("/dashboard");
    const watch = await loadedRegion("AI Watch");
    // Not yet approved, with Not approved and Unreviewed apart (owner, 2026-11-03; D184).
    expect(within(watch).getByText("AI services not yet approved")).toBeVisible();
    expect(within(watch).getByText("1 not approved, 1 unreviewed")).toBeVisible();
    expect(within(watch).getByText("People using AI not yet approved")).toBeVisible();
    expect(within(watch).queryByText(/unapproved/i)).toBeNull();
    // Unreviewed links to those alerts, closed ones included (owner, 2026-10-29).
    expect(within(watch).getByRole("link", { name: "Review 1 unreviewed" })).toHaveAttribute(
      "href",
      "/alerts#review",
    );
    expect(within(watch).getByRole("button", { name: "2" })).toBeVisible();
    // The pill sits beside the number; the block says once what it is compared against.
    expect(within(watch).getAllByTitle(/^\+1 vs previous 7 days/)).toHaveLength(2);
    expect(within(watch).getByTitle(/^same as previous 7 days/)).toBeVisible();
    expect(within(watch).getByText("Changes against the previous 7 days")).toBeVisible();
    // People and devices are never one number: devices without a person are their own line.
    expect(
      within(watch).getByRole("button", { name: "2 more devices not matched to a person" }),
    ).toBeVisible();
    // A card without its source takes no card (F62): one muted line with the setup link.
    expect(within(watch).queryByText("App consent grants")).toBeNull();
    expect(within(watch).getByText(/^Not set up:/)).toHaveTextContent(
      "app consent grants (needs a Microsoft 365 source)",
    );
    // Capitals stay on product words: "MCP servers", "AI".
    expect(within(watch).getByText(/^Not set up:/)).not.toHaveTextContent(/mcp servers|to ai\b/);
    expect(within(watch).getByRole("button", { name: "Add a source" })).toBeVisible();
    expect(within(watch).getByText("Restricted")).toBeVisible();
    // New in 24 hours sits under the cards, from first seen.
    expect(within(watch).getByRole("link", { name: "DeepSeek (AI service)" })).toHaveAttribute(
      "href",
      "/alerts#item=w1",
    );
    // One window for the block: the chart shows the cards' 7 days (ADR-0038 row 11).
    expect(
      within(watch).getByRole("img", { name: /^AI use per day over 7 days by review status:/ }),
    ).toBeVisible();
    expect(
      within(watch).getByRole("img", {
        name: /^How this is counted: AI services from the catalog/,
      }),
    ).toBeVisible();
    const top = within(watch).getByRole("table", { name: "Top AI services" });
    expect(within(top).getByRole("link", { name: "DeepSeek" })).toBeVisible();
    expect(within(top).getByText("Not approved")).toBeVisible();
    // Zero people is the number 0, as in the Inventory; "·" is only for an unknown value.
    const gemini = within(top).getByRole("link", { name: "Gemini" }).closest("tr")!;
    expect(gemini.querySelectorAll("td")[2]).toHaveTextContent(/^0$/);
    expect(gemini).not.toHaveTextContent("·");
    // The page window drives the block (ADR-0038 edit 10): no toggle of its own.
    expect(within(watch).queryByRole("button", { name: "30 days" })).toBeNull();
    const win = screen.getByRole("group", { name: "Time window" });
    await userEvent.click(within(win).getByRole("button", { name: "30 days" }));
    await vi.waitFor(() =>
      expect(
        spy.mock.calls.some(([u]) => String(u).includes("/api/ai/watch/summary?days=30")),
      ).toBe(true),
    );
  });

  it("stacks AI use as an area, shades days after the data stops, and shows values on the keys", async () => {
    const { Chart } = await import("@/features/dashboard/AiWatch");
    const chart = Array.from({ length: 30 }, (_, i) => ({
      day: new Date(Date.UTC(2026, 9, i + 1)).toISOString().slice(0, 10),
      approved: i < 25 ? 2 : 0,
      unreviewed: i < 25 ? 3 : 0,
      not_approved: 0,
    }));
    render(<Chart chart={chart} days={7} dataUntil="2026-10-25T18:00:00+00:00" />);
    const img = screen.getByRole("img", { name: /over 7 days/ });
    expect(img).toHaveAccessibleName(/No data after Oct 25\./);
    expect(screen.getByText(/no data after Oct 25/)).toBeVisible();
    img.focus();
    await userEvent.keyboard("{End}");
    expect(screen.getByRole("tooltip")).toHaveTextContent(/Oct 30: No data yet/);
    for (let i = 0; i < 5; i++) await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "Oct 25: Not approved 0, Unreviewed 3, Approved 2, total 5",
    );
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});

describe("A dashboard section that fails to load (F63)", () => {
  it("stays on the page with a plain error and Retry", async () => {
    const real = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
    const impl = real.getMockImplementation() as typeof fetch;
    real.mockRestore();
    window.history.replaceState(null, "", "/dashboard");
    let fail = true;
    vi.spyOn(globalThis, "fetch").mockImplementation((url, init) => {
      if (fail && String(url).includes("/api/ai/watch/summary"))
        return Promise.resolve(
          new Response(
            JSON.stringify({
              detail: "The query needs more memory than this server allows.",
              code: "query_memory",
            }),
            {
              status: 503,
              headers: { "Content-Type": "application/json", "X-Request-ID": "a1b2c3d4e5f6" },
            },
          ),
        );
      return impl(url, init);
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);
    const watch = await loadedRegion("AI Watch");
    const alert = await within(watch).findByRole("alert");
    expect(alert).toHaveTextContent(
      "AI Watch did not load: the query ran out of memory on this server; try a shorter time range.",
    );
    expect(alert).toHaveTextContent("Request a1b2c3d4e5f6");
    // The server is not "unreachable": a limit with a code is an answer.
    expect(screen.queryByText(/cannot reach the server/i)).toBeNull();
    fail = false;
    await userEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await within(watch).findByText("AI services not yet approved")).toBeVisible();
    expect(within(watch).queryByRole("alert")).toBeNull();
  });
});

describe("AI Watch wording and chart (owner nits, 2026-10-29)", () => {
  it("keeps capitals inside the Not set up sentence", async () => {
    const { midSentence } = await import("@/features/dashboard/AiWatch");
    expect(midSentence("New agents and MCP servers")).toBe("new agents and MCP servers");
    expect(midSentence("Sensitive data to AI")).toBe("sensitive data to AI");
    expect(midSentence("MCP servers")).toBe("MCP servers");
    expect(midSentence("App consent grants")).toBe("app consent grants");
  });

  it("covers only the days that exist until there are 30", async () => {
    const { Chart } = await import("@/features/dashboard/AiWatch");
    const chart = Array.from({ length: 30 }, (_, i) => ({
      day: new Date(Date.UTC(2026, 8, 30 + i)).toISOString().slice(0, 10),
      approved: i >= 22 ? 3 : 0, // 8 days of data: Oct 22 to Oct 29
      unreviewed: 0,
      not_approved: 0,
    }));
    render(<Chart chart={chart} />);
    expect(screen.getByText(/^AI use since Oct 22/)).toBeVisible();
    expect(screen.getByRole("img")).toHaveAttribute(
      "aria-label",
      expect.stringContaining("over 8 days"),
    );
  });
});

describe("Dashboard sections (ADR-0038 edit 10)", () => {
  it("shows Identity, Attacks and access, and Detections for the page window", async () => {
    window.localStorage.removeItem("dashboard.window");
    const spy = await renderAt("/dashboard");
    const identity = await loadedRegion("Identity");
    // The comparison note sits beside the title; the action place holds View all (D254).
    const head = identity.querySelector<HTMLElement>("[data-card-header]")!;
    expect(within(head).getByText(/^from Microsoft 365\. Changes against/)).toBeVisible();
    expect(within(identity).getByText("Failed sign-ins")).toBeVisible();
    // Not set: an admin gets the link instead of a number.
    expect(within(identity).getByRole("button", { name: "Set approved countries" })).toBeVisible();
    expect(within(identity).getByText("12 of 400 sign-ins failed (3.0%)")).toBeVisible();
    expect(within(identity).getByRole("link", { name: "dana.k@example.com" })).toBeVisible();
    // Failed sign-ins: an amber line with the window before dashed, values on the keys.
    const trend = within(identity).getByRole("img", { name: /^Failed sign-ins per hour: 12 in/ });
    expect(trend).toHaveAccessibleName(/8 in the window before/);
    trend.focus();
    await userEvent.keyboard("{Home}{ArrowRight}{ArrowRight}{ArrowRight}");
    expect(within(identity).getByRole("tooltip")).toHaveTextContent(
      "Oct 27, 12 AM: Failed sign-ins 4, Same hour last week (Oct 20, 12 AM) 2",
    );
    const attacks = screen.getByRole("region", { name: "Attacks and access" });
    expect(within(attacks).getByText(/office addresses count as external/)).toBeVisible();
    expect(within(attacks).getByRole("img", { name: "bastion: peak 9, total 14" })).toBeVisible();
    // A network name is cut in the middle (D257); its title is the whole name.
    expect(within(attacks).getByTitle("AS64500 Example Net")).toBeVisible();
    // Country and the numbers fit their content and are never cut; Network takes the rest.
    const top = within(attacks).getByRole("table", { name: "Top sources" });
    expect(top).not.toHaveClass("table-fixed");
    expect([...top.querySelectorAll("col")].map((c) => c.className)).toEqual([
      "w-px",
      "",
      "w-px",
      "w-px",
    ]);
    // A phone-width card scrolls sideways rather than overflow, and Network keeps 96px.
    expect(top.parentElement).toHaveClass("max-md:overflow-x-auto");
    expect(top.parentElement).not.toHaveClass("overflow-x-auto");
    const net = top.querySelector<HTMLElement>("tbody td:nth-child(2)")!;
    expect(net).not.toHaveClass("max-w-0");
    expect(net.querySelector("[data-truncate]")).toHaveClass("min-w-24");
    expect(top.querySelector("tbody td:nth-child(1)")).toHaveClass("whitespace-nowrap");
    expect(within(attacks).getByText("No VPN logs")).toBeVisible();
    // The week before is only partly there: no change pills, and one line for the section
    // saying when comparisons start, not a note under every number (owner, 2026-11-02).
    // The date is the server's (`history.starts`): the page does no date math (item 8).
    expect(
      within(attacks).getByText(/^Comparisons start Nov 3, when the window before has data/),
    ).toBeVisible();
    expect(within(attacks).queryByText("Not enough history for comparison")).toBeNull();
    expect(within(attacks).queryByText("↑ 18")).not.toBeInTheDocument();
    expect(within(identity).getByText("↑ 4")).toBeVisible();
    // Addresses with no country say why; the admin is offered the GeoIP update.
    expect(within(attacks).getByText("Not in GeoIP file")).toBeVisible();
    expect(within(attacks).getByRole("note")).toHaveTextContent(
      "3 addresses are not in the GeoIP file (installed Oct 1, 2026).",
    );
    expect(within(attacks).getByRole("button", { name: "Update GeoIP" })).toBeVisible();
    const det = screen.getByRole("region", { name: "Detections" });
    expect(within(det).getByText("of 142 enabled")).toBeVisible();
    // D221: distinct matched events first, rule matches second.
    const matched = within(det).getByText("Matched events").closest("[data-kpi]") as HTMLElement;
    expect(within(matched).getByText("20")).toBeVisible();
    expect(within(matched).getByText("31 rule matches")).toBeVisible();
    expect(within(det).getByText("SSH failed password")).toBeVisible();
    const win = screen.getByRole("group", { name: "Time window" });
    await userEvent.click(within(win).getByRole("button", { name: "24 hours" }));
    await vi.waitFor(() =>
      expect(
        spy.mock.calls.some(([u]) =>
          String(u).includes("/api/dashboard/sections?window=24h&part=identity"),
        ),
      ).toBe(true),
    );
    expect(window.localStorage.getItem("dashboard.window")).toBe("24h");
    // Each section's View all opens its full list: Sign-ins, Logs, Alerts > Rules.
    for (const [name, path] of [
      ["Identity", "/investigate/views"],
      ["Attacks and access", "/investigate/logs"],
      ["Detections", "/alerts/rules"],
    ] as const) {
      const region = await loadedRegion(name);
      const top = region.querySelector<HTMLElement>("[data-card-header]")!;
      const all = within(top).getByRole("button", { name: "View all" });
      expect(top.lastElementChild).toContainElement(all);
      // The sentence about company egress is a body row, not in the header.
      expect(within(top).queryByText(/office addresses/)).toBeNull();
      await userEvent.click(all);
      expect(window.location.pathname).toBe(path);
      act(() => {
        window.history.pushState(null, "", "/dashboard");
        window.dispatchEvent(new PopStateEvent("popstate"));
      });
    }
    window.localStorage.removeItem("dashboard.window");
  });
});

describe("AI Watch: no data after the newest event's own date", () => {
  it("does not claim data until now for old events that arrived just now", async () => {
    await renderAt("/dashboard", undefined, (spy) => {
      const base = spy.getMockImplementation() as typeof fetch;
      spy.mockImplementation(async (input, init) => {
        const res = await base(input, init);
        if (!String(input).endsWith("/api/overview")) return res;
        const o = await res.json();
        // linux_sshd (the source AI Watch read) received records just now, dated Oct 8.
        o.sources = o.sources.map((x: { source_id: string }) =>
          x.source_id === "linux_sshd"
            ? {
                ...x,
                last_event_at: "2026-10-10T12:29:30+00:00",
                newest_event_at: "2026-10-08T09:00:00+00:00",
              }
            : x,
        );
        return new Response(JSON.stringify(o), {
          headers: { "Content-Type": "application/json" },
        });
      });
    });
    expect(await screen.findByText(/no data after Oct 8/)).toBeVisible();
  });
});
