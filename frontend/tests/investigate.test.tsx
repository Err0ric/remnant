import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

async function openInvestigate(path = "/investigations") {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "open" });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
  // The landing is titled People & devices; an entity's page by the entity.
  await screen.findByRole("heading", { level: 1 });
  return spy;
}

afterEach(() => vi.restoreAllMocks());

describe("Entity picker (F56)", () => {
  it("knows an address, a user, and a host from what is typed", async () => {
    const { kindOf } = await import("@/features/investigate/entityKind");
    expect(kindOf("203.0.113.9")).toBe("ip");
    expect(kindOf("2001:db8::1")).toBe("ip");
    expect(kindOf("alice@example.com")).toBe("user");
    expect(kindOf("EXAMPLE\\alice")).toBe("user");
    expect(kindOf("ws-0042")).toBe("host");
    expect(kindOf("999.1.1.1")).toBe("host");
    expect(kindOf("  ")).toBeNull();
  });

  it("has no picker of its own: the top bar search opens people and devices", async () => {
    await openInvestigate();
    expect(screen.queryByRole("textbox", { name: "Entity" })).toBeNull();
    expect(screen.queryByRole("radio", { name: "AI flow" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
  });
});

describe("Entity pages from a link (product pass step 2)", () => {
  it("opens the entity in the address, and Back to all entities clears it", async () => {
    const spy = await openInvestigate("/investigate/people#ip=203.0.113.9");
    await vi.waitFor(() => {
      const call = spy.mock.calls.find(([u]) => String(u).includes("/api/entities/graph"));
      expect(String(call?.[0])).toContain("kind=ip");
      expect(String(call?.[0])).toContain("value=203.0.113.9");
    });
    // The page leads with the answer, then numbers, then what it did with real values.
    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(
      await within(summary).findByText(
        "2,619 failed sign-ins against ftp-01 over the last 7 days, 0 succeeded. From Netherlands, AS64500 Example Net.",
      ),
    ).toBeVisible();
    const acts = within(summary).getByRole("list", { name: "Activities" });
    expect(
      within(acts).getByText("Failed password for root from 203.0.113.9 port 52144 ssh2"),
    ).toBeVisible();
    expect(within(acts).getByRole("link", { name: "ftp-01" })).toHaveAttribute(
      "href",
      "/investigate/people#host=ftp-01",
    );
    expect(within(summary).getByRole("heading", { name: /Users tried/ })).toBeVisible();
    // Sign-ins by outcome, each one click from its rows (D158).
    const slices = within(summary).getByRole("group", { name: "Sign-ins by outcome" });
    for (const label of ["Real failures", "Interrupted", "Expired", "Other", "All"])
      expect(within(slices).getByRole("button", { name: new RegExp(`^${label}`) })).toBeVisible();
    expect(within(slices).getByRole("button", { name: /^Expired/ })).toHaveAttribute(
      "title",
      "Open 0 expired in Logs",
    );
    // A Record page: the entity is the title, and the breadcrumb leads back.
    expect(screen.getByRole("heading", { level: 1, name: "203.0.113.9" })).toBeVisible();
    const crumb = screen.getByRole("navigation", { name: "Breadcrumb" });
    await userEvent.click(within(crumb).getByRole("link", { name: "People & devices" }));
    expect(window.location.hash).toBe("");
    expect(screen.getByRole("heading", { level: 1, name: "People & devices" })).toBeVisible();
  });

  it("names the Proxmox guest on a host page, with Show events (ADR-0045 A5)", async () => {
    await openInvestigate("/investigate/people#host=build-runner");
    const summary = await screen.findByRole("region", { name: "Summary" });
    const inv = await within(summary).findByRole("list", { name: "Proxmox inventory" });
    expect(inv).toHaveTextContent("Proxmox VM 104 build-runner on pve2");
    await userEvent.click(within(inv).getByRole("button", { name: "Show events" }));
    expect(window.location.pathname).toBe("/investigate/logs");
  });

  it("opens an AI service in the AI flow", async () => {
    const spy = await openInvestigate("/investigate/people#service=chatgpt");
    expect(await screen.findByRole("group", { name: /People, AI clients/ })).toBeVisible();
    await vi.waitFor(() => {
      const call = spy.mock.calls.find(([u]) => String(u).includes("mode=ai"));
      expect(String(call?.[0])).toContain("value=chatgpt");
    });
  });
});

describe("Investigations (ADR-0016)", () => {
  it("ranks entities with the score's parts and opens one in lanes", async () => {
    const spy = await openInvestigate();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: "People & devices" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    const table = await screen.findByRole("table", { name: "User" });
    expect(within(table).getByText("4 high")).toBeVisible();
    await userEvent.click(within(table).getByRole("button", { name: "root" }));
    // A person's lanes are folded: nothing is asked for them until they are opened.
    expect(spy.mock.calls.some(([u]) => String(u).includes("/api/entities/graph"))).toBe(false);
    await userEvent.click(await screen.findByRole("button", { name: "How it connects" }));
    const lanes = await screen.findByRole("group", { name: /Investigation lanes/ });
    for (const lane of ["Entity", "Sources", "Activities", "Targets"])
      expect(within(lanes).getByText(lane)).toBeInTheDocument();
    expect(within(lanes).getByText("2 more not shown (smaller ones)")).toBeInTheDocument();
    const call = spy.mock.calls.find(([u]) => String(u).includes("/api/entities/graph"));
    expect(String(call?.[0])).toContain("kind=user");
    expect(String(call?.[0])).toContain("value=root");
  });

  it("uses the page's full width, a neutral score bar, and no count beside the title", async () => {
    await openInvestigate();
    const table = await screen.findByRole("table", { name: "User" });
    const card = screen.getByRole("region", { name: "Most active entities" });
    expect(card.className).not.toMatch(/max-w-|mx-auto/);
    // The tabs carry the counts; the title has none (it said "0 rule matches considered").
    expect(screen.queryByText(/rule matches considered/)).toBeNull();
    const erin = within(table).getByRole("button", { name: "erin@example.com" }).closest("tr")!;
    const fill = within(erin)
      .getByTitle(/Score: 14/)
      .querySelector("span > span")!;
    // A magnitude, never a severity or a state color.
    expect(fill.className).toContain("bg-text-secondary");
    expect(fill.className).not.toMatch(/danger|sev-/);
  });

  it("lays out every tab on one column scheme, numbers right-aligned", async () => {
    const { LEAD_COL, NAME_COL, restCol } = await import("@/features/investigate/listColumns");
    await openInvestigate();
    await screen.findByRole("table", { name: "User" });
    const tabs: [RegExp, string][] = [
      [/^Users/, "User"],
      [/^IP addresses/, "Source IP"],
      [/^Hosts/, "Host"],
      [/^Targeted usernames/, "Targeted usernames"],
    ];
    for (const [tab, name] of tabs) {
      await userEvent.click(screen.getByRole("tab", { name: tab }));
      const table = await screen.findByRole("table", { name });
      const heads = within(table).getAllByRole("columnheader");
      const [first, lead, ...rest] = heads;
      // The name and the lead number (score or attempts) take the shared widths.
      for (const c of NAME_COL.split(" ")) expect(first!.className).toContain(c);
      for (const c of LEAD_COL.split(" ")) expect(lead!.className).toContain(c);
      expect(lead!.className).toContain("text-right");
      // Every other column asks for the same equal share, on one line.
      for (const h of rest) {
        expect(parseFloat(h.style.width)).toBeCloseTo(
          parseFloat(String(restCol(rest.length).width)),
          2,
        );
        expect(h.className).toContain("whitespace-nowrap");
      }
      if (name !== "Targeted usernames") {
        // Rule matches is a number column like the rest: header and values to the right.
        const rule = heads.find((h) => h.textContent === "Rule matches")!;
        expect(rule.className).toContain("text-right");
        const col = heads.indexOf(rule);
        for (const row of within(table).getAllByRole("row").slice(1)) {
          const cell = row.querySelectorAll("td")[col]!;
          expect(cell.querySelector("div")!.className).toContain("justify-end");
        }
      } else {
        const attempts = within(table).getAllByRole("row")[1]!.querySelectorAll("td")[1]!;
        expect(attempts.className).toContain("text-right");
        expect(attempts.className).toContain("whitespace-nowrap");
      }
    }
  });

  it("lists everyone seen, with a column per signal and the score's parts on hover (D195)", async () => {
    await openInvestigate();
    const table = await screen.findByRole("table", { name: "User" });
    const heads = within(table)
      .getAllByRole("columnheader")
      .map((h) => h.getAttribute("aria-label") ?? h.textContent);
    // How the score adds up is on its column (it was a paragraph under the table); what
    // is counted, by access, stays on the page.
    const rule = within(table).getByRole("img", { name: /^How this is counted: 10 per critical/ });
    expect(rule).toHaveAttribute("title", expect.stringContaining("Only sources you may read"));
    expect(screen.getByText("Only sources you may read are counted.")).toBeVisible();
    expect(screen.queryByText(/^Everyone seen in this range/)).toBeNull();
    expect(heads).toEqual([
      "User",
      "Score",
      "Rule matches",
      "Failed sign-ins",
      "Risky inbox rules",
      "App consents",
      "AI watch flags",
      "Alerts",
      "Events",
    ]);
    const erin = within(table).getByRole("button", { name: "erin@example.com" }).closest("tr")!;
    expect(
      within(erin).getByTitle(
        /Failed sign-ins: 3\sRisky inbox rules: 5\sAI watch flags: 6\sScore: 14/,
      ),
    ).toBeVisible();
    expect(within(erin).getByTitle("personal Claude account, new MCP server")).toHaveTextContent(
      "2",
    );
    // No rule match and no signal: still listed, last, by its events.
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.at(-1)).toHaveTextContent("jordan");
    expect(
      within(rows.at(-1)!).getByTitle("Nothing adds to the score in this range"),
    ).toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: /^Hosts/ }));
    const hosts = await screen.findByRole("table", { name: "Host" });
    expect(
      within(hosts)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toContain("Attack hits");
    expect(
      within(hosts).getByTitle(/Failed sign-ins: 25 \(capped\)\sAttack hits: 25 \(capped\)/),
    ).toBeVisible();
    expect(screen.getByText(/Only sources you may read are counted\./)).toBeVisible();
  });

  it("lists usernames only tried from outside apart from users (D212)", async () => {
    const spy = await openInvestigate();
    const users = await screen.findByRole("table", { name: "User" });
    expect(within(users).queryByText("minecraft")).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "Targeted usernames (2)" }));
    const table = await screen.findByRole("table", { name: "Targeted usernames" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual([
      "Username",
      "Attempts",
      "Sources",
      "Top countries",
      "Top networks (ASN)",
      "Hosts targeted",
    ]);
    const row = within(table).getByRole("button", { name: "minecraft" }).closest("tr")!;
    expect(row).toHaveTextContent("1,240");
    expect(row).toHaveTextContent("Netherlands 900, Brazil 340");
    expect(row).toHaveTextContent("AS64500 Example Net 900");
    expect(row).toHaveTextContent("bastion, web-01");
    // Enrichment off for this one: the place cells are empty, not "unknown".
    const ubuntu = within(table).getByRole("button", { name: "ubuntu" }).closest("tr")!;
    expect(within(ubuntu).getAllByRole("cell")[3]).toHaveTextContent(/^$/);
    await userEvent.click(within(table).getByRole("button", { name: "minecraft" }));
    await userEvent.click(await screen.findByRole("button", { name: "How it connects" }));
    await screen.findByRole("group", { name: /Investigation lanes/ });
    const call = spy.mock.calls.find(([u]) => String(u).includes("value=minecraft"));
    expect(String(call?.[0])).toContain("kind=user");
  });

  it("highlights a card's path and hands its events to Search", async () => {
    await openInvestigate("/investigate/people#user=root");
    await userEvent.click(await screen.findByRole("button", { name: "How it connects" }));
    const card = await screen.findByRole("button", { name: /Activities: Failed password/ });
    await userEvent.click(card);
    expect(card).toHaveAttribute("aria-pressed", "true");
    const other = screen.getByRole("button", { name: /Activities: Accepted publickey/ });
    expect(other.getAttribute("class")).toContain("opacity-40");
    const detail = screen.getByRole("region", { name: "Selected card" });
    expect(within(detail).getByText("Authentication")).toBeVisible();
    await userEvent.click(within(detail).getByRole("button", { name: "Open in Logs" }));
    await screen.findByRole("heading", { level: 1, name: "Logs" });
    expect(window.location.pathname).toBe("/investigate/logs");
    // Search opens over the same range the investigation used (Last 7 days by default).
    expect(
      within(screen.getByRole("group", { name: "Time" })).getByRole("button", { name: "7 days" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("shows the AI flow with Not approved badges and follows a person", async () => {
    const spy = await openInvestigate("/investigate/people#service=chatgpt");
    const lanes = await screen.findByRole("group", { name: /People, AI clients/ });
    const tool = within(lanes).getByRole("button", { name: /paste-share.*Not approved/ });
    expect(tool).toBeInTheDocument();
    await userEvent.click(within(lanes).getByRole("button", { name: /People: alice@example.com/ }));
    await userEvent.click(screen.getByRole("button", { name: "Investigate this" }));
    expect(await screen.findByText("Showing AI flow for")).toBeVisible();
    const last = spy.mock.calls.filter(([u]) => String(u).includes("/api/entities/graph")).at(-1);
    expect(String(last?.[0])).toContain("mode=ai");
    expect(String(last?.[0])).toContain("value=alice%40example.com");
  });

  it("shows machines for people without View people in AI usage, never to follow (D242)", async () => {
    window.history.replaceState(null, "", "/investigate/people#service=chatgpt");
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) => {
      const res = await base(input, init);
      if (!String(input).includes("/api/entities/graph")) return res;
      const g = await res.json();
      g.masked = true;
      g.cards[0] = { ...g.cards[0], id: "0:row-0", label: "ws-0042" };
      g.edges[0] = { ...g.edges[0], source: "0:row-0" };
      return new Response(JSON.stringify(g), { headers: { "content-type": "application/json" } });
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);
    const lanes = await screen.findByRole("group", { name: /People, AI clients/ });
    expect(
      screen.getByText("Names are hidden. An admin can turn on View people in AI usage for you."),
    ).toBeVisible();
    await userEvent.click(within(lanes).getByRole("button", { name: /People: ws-0042/ }));
    const detail = screen.getByRole("region", { name: "Selected card" });
    expect(within(detail).getByText("ws-0042")).toBeVisible();
    expect(within(detail).queryByRole("button", { name: "Investigate this" })).toBeNull();
  });

  it("renders attacker-controlled labels as text", async () => {
    await openInvestigate(
      `/investigate/people#user=${encodeURIComponent("<img src=x onerror=alert(1)>")}`,
    );
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("<img src=x");
    await userEvent.click(await screen.findByRole("button", { name: "How it connects" }));
    const lanes = await screen.findByRole("group", { name: /Investigation lanes/ });
    expect(lanes.querySelector("img")).toBeNull();
    expect(within(lanes).getAllByText(/<img src=x/).length).toBeGreaterThan(0);
  });
});

describe("Person record, Microsoft 365 table (owner, 2026-11-16)", () => {
  it("pages a long list instead of scrolling inside the page, with plain headers and no person or device column", async () => {
    window.history.replaceState(null, "", "/investigate/people#user=alice");
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    const columns = ["time", "actor_user_name", "app", "outcome", "src_endpoint_ip"];
    const rows = Array.from({ length: 140 }, (_, i) => [
      new Date(Date.UTC(2026, 9, 30, 12) - i * 60_000).toISOString(),
      "alice@example.com",
      "Office 365 Exchange Online",
      "Success",
      `198.51.100.${i % 250}`,
    ]);
    spy.mockImplementation(async (input, init) => {
      if (!/\/api\/people\/[^/]+\/m365\?name=sign_ins/.test(String(input)))
        return base(input, init);
      const body = {
        columns,
        rows,
        row_count: rows.length,
        truncated: false,
        elapsed_ms: 3,
        executed_sql: "SELECT 1",
        sources: ["m365"],
        geo: {},
        intel: {},
      };
      return new Response(JSON.stringify(body), {
        headers: { "content-type": "application/json" },
      });
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);
    const m365 = await screen.findByRole("region", { name: "Microsoft 365" });
    const grid = await within(m365).findByRole("treegrid");
    // No box of its own height around the table: the page scrolls, the table pages.
    for (let el = grid.parentElement; el && el !== m365; el = el.parentElement) {
      expect(el.className).not.toMatch(/max-h-|overflow-y-auto/);
    }
    expect(within(grid).getAllByRole("row")).toHaveLength(51); // the header and 50 rows
    const ranges = within(m365).getAllByText(/^1 to 50 of 140/);
    expect(ranges.length).toBe(2); // above and below the rows
    expect(
      within(grid)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["", "Time", "App", "Outcome", "Source IP"]);
    // A long app name is cut in the middle, the whole name on hover.
    const app = within(grid).getAllByText(
      (_, el) => el?.getAttribute("data-truncate") === "name",
    )[0]!;
    expect(app).toHaveAttribute("title", "Office 365 Exchange Online");
    await userEvent.click(within(m365).getAllByRole("button", { name: "Next" })[0]!);
    expect(within(m365).getAllByText(/^51 to 100 of 140/).length).toBe(2);
  });
});

describe("Person timeline (ADR-0038 section 9)", () => {
  it("shows the forms of the name and rows by day, each opening its events", async () => {
    await openInvestigate("/investigate/people#user=alice");
    await userEvent.click(await screen.findByRole("button", { name: "Timeline" }));
    const box = await screen.findByRole("region", { name: "Timeline" });
    expect(await within(box).findByText(/EXAMPLE\\alice, alice@example.com/)).toBeVisible();
    const days = within(box).getByRole("list", { name: "Activity by day" });
    expect(within(days).getAllByRole("heading", { level: 3 })).toHaveLength(2);
    const failed = within(box).getByRole("button", { name: "Failed to Office 365" });
    expect(failed).toHaveAttribute("title", "Open 2 events in Logs");
    await userEvent.click(failed);
    expect(await screen.findByText(/From alice > Timeline/)).toBeVisible();
  });

  it("is one Record per person: a sentence, numbers, then alerts, activity, Microsoft 365, AI use (ADR-0052)", async () => {
    const spy = await openInvestigate("/investigate/people#user=alice");
    expect(screen.getByRole("heading", { level: 1, name: "alice" })).toBeVisible();
    expect(screen.queryByRole("tablist", { name: "Person" })).toBeNull();
    // The page's one filled button.
    const primary = await screen.findByRole("button", { name: "Open in Logs" });
    expect(primary).toHaveAttribute("data-primary");
    const summary = await screen.findByRole("region", { name: "Summary" });
    const kpi = (label: string) => summary.querySelector(`[data-kpi="${label}"]`) as HTMLElement;
    // Devices, Addresses, and AI services count whole days back from now and say so.
    await vi.waitFor(() => expect(kpi("Devices")).toHaveTextContent("1Last 7 days"));
    expect(kpi("Sign-ins")).not.toHaveTextContent("Last 7 days");
    expect(kpi("Addresses")).toHaveTextContent("1");
    expect(kpi("Sign-ins")).toHaveTextContent("2,619");
    for (const label of ["Open alerts", "AI services"]) expect(kpi(label)).toBeVisible();
    expect(await screen.findByRole("region", { name: "Open alerts" })).toBeVisible();
    // Activity per day: a bar opens that day's events in Logs; an empty day opens nothing.
    const days = within(await screen.findByRole("region", { name: "Activity per day" })).getByRole(
      "list",
      { name: "Events per day" },
    );
    expect(within(days).getByRole("button", { name: /^Oct 28: 0 events/ })).toBeDisabled();
    expect(
      within(days).getByRole("button", {
        name: "Oct 30: 30 events, 2 failed sign-ins. Open in Logs",
      }),
    ).toBeEnabled();
    // Microsoft 365: one table with a switch; times local with UTC on hover, never the raw
    // UTC string (review item 6).
    const m365 = await screen.findByRole("region", { name: "Microsoft 365" });
    const at = await within(m365).findByText("Oct 30, 9:58:00 AM"); // tests run in UTC; log tables keep seconds
    expect(at.tagName).toBe("TIME");
    expect(at).toHaveAttribute("title", "2026-10-30 09:58 UTC");
    const pick = within(m365).getByRole("group", { name: "Microsoft 365 list" });
    await userEvent.click(within(pick).getByRole("button", { name: "Mail" }));
    // The operation, cut in the middle when long, keeps its whole name on hover.
    expect(await within(m365).findByTitle("new-inboxrule")).toBeVisible();
    expect(spy.mock.calls.some(([u]) => String(u).includes("/m365?name=mail&days=7"))).toBe(true);
    await userEvent.click(within(pick).getByRole("button", { name: "Admin" }));
    expect(
      await within(m365).findByText(
        "No Microsoft 365 directory changes by this person in this range.",
      ),
    ).toBeVisible();
    // The side column: the names counted as the person, devices, addresses.
    const side = screen.getByRole("complementary", { name: "Accounts, devices, and addresses" });
    expect(within(side).getByRole("list", { name: "Accounts" })).toHaveTextContent(
      "alice@example.com",
    );
    const devices = within(side).getByRole("table", { name: "Devices" });
    expect(within(devices).getByRole("link", { name: "ws-0042" })).toBeVisible();
    // Every row, with events, failed sign-ins, and last seen, as the old tab had.
    const address = within(within(side).getByRole("table", { name: "Addresses" }))
      .getByRole("link", { name: "203.0.113.10" })
      .closest("tr")!;
    expect(
      within(address)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["203.0.113.10", "12", "3", "Oct 28, 6:00 PM"]);
    // These lists count whole days back from now and say so (owner, 2026-11-13).
    expect(within(side).getAllByText("Last 7 days").length).toBe(2);
    // Another person is another page: a fold opened here is closed there, and its lanes
    // are asked for again when opened.
    await userEvent.click(screen.getByRole("button", { name: "How it connects" }));
    await screen.findByRole("group", { name: /Investigation lanes/ });
    window.location.hash = "user=bob";
    await vi.waitFor(() =>
      expect(screen.getByRole("button", { name: "How it connects" })).toHaveAttribute(
        "aria-expanded",
        "false",
      ),
    );
    window.location.hash = "user=alice";
    await screen.findByRole("heading", { level: 1, name: "alice" });
    // The timeline is read only when opened.
    expect(spy.mock.calls.some(([u]) => String(u).includes("/timeline?"))).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Timeline" }));
    const box = await screen.findByRole("region", { name: "Timeline" });
    await userEvent.click(
      await within(box).findByRole("button", { name: "Sensitive data to AI: alice" }),
    );
    expect(window.location.pathname + window.location.hash).toBe("/alerts#item=a1");
  });

  it("opens a Microsoft 365 list in Logs with the page's window", async () => {
    await openInvestigate("/investigate/people#user=alice");
    const m365 = await screen.findByRole("region", { name: "Microsoft 365" });
    await userEvent.click(within(m365).getByRole("button", { name: "Open in Logs" }));
    expect(await screen.findByText(/^From alice > Sign-ins, Oct 23/)).toBeVisible();
  });

  it("opens a day in Logs, cut to the page's window", async () => {
    await openInvestigate("/investigate/people#user=alice");
    const days = await screen.findByRole("list", { name: "Events per day" });
    // The window ends at 12:00 on Oct 30 (tests run in UTC): the last bar counted only
    // that morning, so Logs gets midnight to 12:00, not the whole day.
    await userEvent.click(within(days).getByRole("button", { name: /^Oct 30: 30 events/ }));
    await screen.findByRole("heading", { level: 1, name: "Logs" });
    expect(await screen.findByText(/^From alice > Activity per day/)).toBeVisible();
    expect(screen.getByLabelText("From")).toHaveValue("2026-10-30T00:00");
    expect(screen.getByLabelText("To")).toHaveValue("2026-10-30T12:00");
  });

  it("shows no Microsoft 365 section without a Microsoft 365 source", async () => {
    window.history.replaceState(null, "", "/investigate/people#user=alice");
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) => {
      const res = await base(input, init);
      if (!/\/record\?/.test(String(input))) return res;
      return new Response(JSON.stringify({ ...(await res.json()), m365: false, m365_sql: {} }), {
        headers: { "content-type": "application/json" },
      });
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);
    expect(await screen.findByRole("region", { name: "Activity per day" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Microsoft 365" })).toBeNull();
    expect(spy.mock.calls.some(([u]) => String(u).includes("/m365?"))).toBe(false);
  });
});

describe("A person's AI activity (D189)", () => {
  it("is on the page from a link that names it, with flags, sessions, and rollups", async () => {
    const spy = await openInvestigate(
      `/investigate/people#user=${encodeURIComponent("alice@example.com")}&tab=ai`,
    );
    expect(await screen.findByRole("heading", { level: 2, name: "AI use" })).toBeVisible();
    const page = await screen.findByRole("region", { name: "AI activity" });
    expect(within(page).getAllByText(/^Last 7 days/).length).toBeGreaterThanOrEqual(2);
    const flags = within(page).getByRole("region", { name: "Flags" });
    expect(flags).toHaveTextContent("Writes outside the session's working folder 1: /etc/hosts");
    expect(flags).toHaveTextContent("Personal Claude account");
    expect(within(page).getByRole("region", { name: "Accounts and devices" })).toHaveTextContent(
      "alice@example.net",
    );
    expect(within(page).getByRole("link", { name: "ChatGPT" })).toBeVisible();
    expect(within(page).getByRole("region", { name: "Claude Code sessions" })).toHaveTextContent(
      "1 prompt; 5 tool calls (Bash, Edit, WebFetch)",
    );
    expect(within(page).getByRole("region", { name: "Commands" })).toHaveTextContent("git");
    expect(within(page).getByRole("region", { name: "MCP servers" })).toHaveTextContent(
      "No MCP servers",
    );
    // The person is the entity, not "alice@example.com&tab=ai".
    expect(String(spy.mock.calls.find(([u]) => String(u).includes("/activity?"))?.[0])).toContain(
      "/api/ai/people/alice%40example.com/activity?days=7",
    );
  });

  it("is where AI usage and Agents send a person", async () => {
    const { entityHref } = await import("@/lib/entity");
    expect(entityHref({ kind: "user", value: "dana@example.com" }, "ai")).toBe(
      "/investigate/people#user=dana%40example.com&tab=ai",
    );
  });
});

describe("A person's AI activity without View people in AI usage (D242)", () => {
  const NEEDS = "Needs View people in AI usage";
  async function open(analyst: boolean, refused = false, viewPeople = false) {
    window.history.replaceState(null, "", "/investigate/people#user=alice%40example.com&tab=ai");
    const spy = analyst
      ? mockApi("Codename", { mode: "login", signedIn: true, role: "analyst", viewPeople })
      : mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    if (refused)
      spy.mockImplementation(async (input, init) =>
        String(input).includes("/activity?")
          ? new Response(JSON.stringify({ detail: NEEDS, code: "forbidden" }), {
              status: 403,
              headers: { "content-type": "application/json" },
            })
          : base(input, init),
      );
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);
    const masked = analyst && !viewPeople;
    await screen.findByRole("heading", {
      level: 1,
      name: masked ? "Name hidden" : "alice@example.com",
    });
    return spy;
  }

  it("masks the title, the header, and the Accounts list", async () => {
    await open(true);
    const title = screen.getByRole("heading", { level: 1 });
    expect(title).toHaveTextContent("Name hidden");
    expect(title).not.toHaveClass("font-mono");
    // The header row: breadcrumb, title, and the kind beside it; none names the person.
    const header = title.closest(".grid") as HTMLElement;
    expect(within(header).getByRole("navigation", { name: "Breadcrumb" })).toBeVisible();
    expect(header.querySelector("[data-header-count]")).toHaveTextContent("Person");
    expect(header).not.toHaveTextContent(/alice/i);
    expect(document.title).not.toMatch(/alice/i);
    const accounts = screen.getByRole("complementary", {
      name: "Accounts, devices, and addresses",
    });
    expect(await within(accounts).findByText("2 names hidden")).toBeVisible();
    expect(within(accounts).queryByRole("list", { name: "Accounts" })).toBeNull();
    expect(within(accounts).queryByText(/EXAMPLE|alice@example\.com/)).toBeNull();
  });

  it("leaves the by-name label out of What it did, and names no one to Logs", async () => {
    await open(true);
    const acts = await screen.findByRole("list", { name: "Activities" });
    // The mock's activity is by "root": the label repeats the names counted as the person.
    expect(within(acts).queryByRole("link", { name: "root" })).toBeNull();
    expect(within(acts).queryByText(/\bby\b/)).toBeNull();
    const m365 = await screen.findByRole("region", { name: "Microsoft 365" });
    await userEvent.click(within(m365).getByRole("button", { name: "Open in Logs" }));
    expect(await screen.findByText(/^From this person > Sign-ins/)).toBeVisible();
    expect(screen.queryByText(/^From alice/)).toBeNull();
  });

  it("shows no name in the Timeline fold", async () => {
    const spy = await open(true);
    await userEvent.click(screen.getByRole("button", { name: "Timeline" }));
    const box = await screen.findByRole("region", { name: "Timeline" });
    expect(await within(box).findByText(/2 names hidden/)).toBeVisible();
    expect(within(box).queryByText(/Seen as/)).toBeNull();
    expect(within(box).queryByText(/Possibly the same person/)).toBeNull();
    expect(box).not.toHaveTextContent(/alice/i);
    expect(spy.mock.calls.some(([u]) => String(u).includes("/timeline?days="))).toBe(true);
  });

  it("shows no name in How it connects", async () => {
    await open(true);
    await userEvent.click(screen.getByRole("button", { name: "How it connects" }));
    const root = await screen.findByRole("button", { name: /^Entity: Name hidden/ });
    expect(root).not.toHaveTextContent(/alice/i);
    await userEvent.click(root);
    const detail = screen.getByRole("region", { name: "Selected card" });
    expect(detail).toHaveTextContent("Name hidden");
    expect(detail).not.toHaveTextContent(/alice/i);
  });

  it("says this person when How it connects is empty", async () => {
    const spy = await open(true);
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) => {
      if (!String(input).includes("/api/entities/graph")) return base(input, init);
      const res = await base(input, init);
      const g = (await res.json()) as { cards: { lane: number }[]; edges: unknown[] };
      return new Response(
        JSON.stringify({ ...g, cards: g.cards.filter((c) => c.lane === 0), edges: [] }),
        { headers: { "content-type": "application/json" } },
      );
    });
    await userEvent.click(screen.getByRole("button", { name: "How it connects" }));
    expect(
      await screen.findByText(
        "No events for this person in this range, in the sources you may read.",
      ),
    ).toBeVisible();
  });

  it("keeps the name as the title with the permission", async () => {
    await open(true, false, true);
    const title = screen.getByRole("heading", { level: 1 });
    expect(title).toHaveTextContent("alice@example.com");
    expect(title).toHaveClass("font-mono");
    const list = await screen.findByRole("list", { name: "Accounts" });
    expect(within(list).getByText("EXAMPLE\\alice")).toBeVisible();
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("says what is needed and never asks the server", async () => {
    const spy = await open(true);
    expect(await screen.findByText(NEEDS)).toBeVisible();
    // The state notice sits above the summary, and the AI number reads Hidden, never 0.
    expect(screen.getByRole("note")).toHaveTextContent(
      "Names are hidden: this person's name and AI activity are not shown.",
    );
    const tile = document.querySelector('[data-kpi="AI services"]') as HTMLElement;
    expect(tile).toHaveTextContent("Hidden");
    expect(screen.queryByRole("region", { name: "AI activity" })).toBeNull();
    expect(spy.mock.calls.some(([u]) => String(u).includes("/activity?"))).toBe(false);
  });

  it("still lists the person's alerts: the server leaves AI Watch items out", async () => {
    const spy = await open(true);
    const box = await screen.findByRole("region", { name: "Open alerts" });
    expect(within(box).queryByText(NEEDS)).toBeNull();
    await vi.waitFor(() =>
      expect(spy.mock.calls.some(([u]) => String(u).includes("person=alice"))).toBe(true),
    );
  });

  it("shows the plain message when the server refuses", async () => {
    const spy = await open(false, true);
    expect(await screen.findByText(NEEDS)).toBeVisible();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(spy.mock.calls.some(([u]) => String(u).includes("/activity?"))).toBe(true);
  });
});

describe("People & devices: Open in Logs with a Custom range", () => {
  it("hands the Custom range on, so Logs reads the same window", async () => {
    await openInvestigate("/investigate/people#user=root");
    const time = screen.getByRole("group", { name: "Time" });
    await userEvent.click(within(time).getByRole("button", { name: "Custom" }));
    // Custom opens on the window that was showing: 7 days back, no end.
    const from = screen.getByLabelText("From") as HTMLInputElement;
    expect(Date.now() - new Date(from.value).getTime()).toBeGreaterThan(6.9 * 86_400_000);
    expect(screen.getByLabelText("To")).toHaveValue("");
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(from, { target: { value: "2026-11-01T08:00" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-11-02T08:00" } });
    await userEvent.click(await screen.findByRole("button", { name: "How it connects" }));
    await userEvent.click(
      await screen.findByRole("button", { name: /Activities: Failed password/ }),
    );
    const detail = screen.getByRole("region", { name: "Selected card" });
    await userEvent.click(within(detail).getByRole("button", { name: "Open in Logs" }));
    await screen.findByRole("heading", { level: 1, name: "Logs" });
    expect(
      within(screen.getByRole("group", { name: "Time" })).getByRole("button", { name: "Custom" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("From")).toHaveValue("2026-11-01T08:00");
    expect(screen.getByLabelText("To")).toHaveValue("2026-11-02T08:00");
  });
});

describe("People & devices: the time filter (ADR-0052 section 3.7; owner, 2026-11-13)", () => {
  const asked = (spy: ReturnType<typeof mockApi>, path: string) =>
    spy.mock.calls.map(([u]) => new URL(String(u), "http://x")).filter((u) => u.pathname === path);

  it("has the five choices, opens on 7 days, and asks for Custom with a start and an end", async () => {
    const spy = await openInvestigate();
    const time = screen.getByRole("group", { name: "Time" });
    expect(
      within(time)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["1 hour", "24 hours", "7 days", "30 days", "Custom"]);
    expect(within(time).getByRole("button", { name: "7 days" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.queryByText(/All time/)).toBeNull();
    await vi.waitFor(() => expect(asked(spy, "/api/entities/risk").length).toBeGreaterThan(0));
    expect(asked(spy, "/api/entities/risk").at(-1)?.searchParams.get("end")).toBeNull();

    await userEvent.click(within(time).getByRole("button", { name: "Custom" }));
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-11-01T08:00" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-11-02T08:00" } });
    await vi.waitFor(() =>
      expect(asked(spy, "/api/entities/risk").at(-1)?.searchParams.get("end")).toBe(
        new Date("2026-11-02T08:00:59.999").toISOString(),
      ),
    );
    expect(asked(spy, "/api/entities/risk").at(-1)?.searchParams.get("start")).toBe(
      new Date("2026-11-01T08:00").toISOString(),
    );
    // The inventory lines of the address list read the same window.
    await userEvent.click(await screen.findByRole("tab", { name: /^IP addresses/ }));
    await vi.waitFor(() =>
      expect(asked(spy, "/api/inventory/matches").at(-1)?.searchParams.get("end")).toBe(
        new Date("2026-11-02T08:00:59.999").toISOString(),
      ),
    );
    // The fragment names what is open on this page; the time is not written into it.
    expect(window.location.hash).toBe("");
  });
});

describe("The address page's sections (P4)", () => {
  it("asks for each section on its own and says what each read", async () => {
    const spy = await openInvestigate("/investigate/people#ip=203.0.113.9");
    const dns = await screen.findByRole("region", { name: "Names looked up" });
    expect(await within(dns).findByText("chatgpt.com")).toBeVisible();
    expect(within(dns).getByText("2 names")).toBeVisible();
    expect(dns).toHaveTextContent("From DNS (dns)");
    expect(
      within(dns).getByRole("img", { name: /the library query Query dns/ }),
    ).toBeInTheDocument();
    // A count opens its events in Logs, with the server's SQL.
    await userEvent.click(within(dns).getByRole("button", { name: "3" }));
    expect(window.location.pathname).toBe("/investigate/logs");
    window.history.back();
    const calls = spy.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/sections/"));
    for (const name of ["dhcp", "dns", "access", "ai"])
      expect(calls.some((u) => u.includes(`/api/addresses/203.0.113.9/sections/${name}?`))).toBe(
        true,
      );
  });

  it("shows a section with no source, an empty one, and a failed one apart", async () => {
    await openInvestigate("/investigate/people#ip=203.0.113.9");
    const dhcp = await screen.findByRole("region", { name: "DHCP and VPN history" });
    expect(
      await within(dhcp).findByText(
        "None of the sources you may read is set to Palo Alto system or GlobalProtect, so nothing was read.",
      ),
    ).toBeVisible();
    const ai = screen.getByRole("region", { name: "AI services" });
    // Empty: one line beside the title, the sources checked on hover.
    expect(await within(ai).findByText("None in the last 7 days")).toHaveAttribute(
      "title",
      "Checked 1 source: dns",
    );
    const access = screen.getByRole("region", { name: "Sign-ins and access" });
    expect(await within(access).findByRole("alert")).toHaveTextContent(
      "This section took too long",
    );
  });

  it("marks a success from an address on its KPI only, in warn, with what it counts", async () => {
    await openInvestigate("/investigate/people#ip=198.51.100.23");
    const summary = await screen.findByRole("region", { name: "Summary" });
    const kpi = within(summary).getByText("Succeeded").closest("div") as HTMLElement;
    expect(kpi).toHaveAttribute("title", "Sign-ins that succeeded from this address");
    expect(within(kpi).getByText("3")).toHaveClass("text-warn");
    expect(within(kpi).getByText("3")).not.toHaveClass("text-danger");
    // The outcome badges stay the app's one mapping: Failed is the failure tag.
    const acts = within(summary).getByRole("list", { name: "Activities" });
    expect(within(acts).getByText("Failed")).toHaveClass("text-danger");
  });

  it("opens on the window its link names (an Ask answer's 7 days, D276)", async () => {
    const spy = await openInvestigate("/investigate/people#ip=203.0.113.9&range=30d");
    await screen.findByRole("region", { name: "Summary" });
    await vi.waitFor(() => {
      const call = spy.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/sections/"));
      expect(call.length).toBeGreaterThan(0);
    });
    expect(screen.getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");
  });

  it("is only on an address's page", async () => {
    const spy = await openInvestigate("/investigate/people#host=ftp-01");
    await screen.findByRole("region", { name: "Summary" });
    expect(spy.mock.calls.some(([u]) => String(u).includes("/sections/"))).toBe(false);
  });
});
