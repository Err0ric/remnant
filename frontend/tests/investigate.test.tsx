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
  await screen.findByRole("heading", { level: 1, name: "People & devices" });
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
    await userEvent.click(screen.getByRole("button", { name: /All entities/ }));
    expect(window.location.hash).toBe("");
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
    const lanes = await screen.findByRole("group", { name: /Investigation lanes/ });
    for (const lane of ["Entity", "Sources", "Activities", "Targets"])
      expect(within(lanes).getByText(lane)).toBeInTheDocument();
    expect(within(lanes).getByText("2 more not shown (smaller ones)")).toBeInTheDocument();
    const call = spy.mock.calls.find(([u]) => String(u).includes("/api/entities/graph"));
    expect(String(call?.[0])).toContain("kind=user");
    expect(String(call?.[0])).toContain("value=root");
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
    await screen.findByRole("group", { name: /Investigation lanes/ });
    const call = spy.mock.calls.find(([u]) => String(u).includes("value=minecraft"));
    expect(String(call?.[0])).toContain("kind=user");
  });

  it("highlights a card's path and hands its events to Search", async () => {
    await openInvestigate("/investigate/people#user=root");
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
    const lanes = await screen.findByRole("group", { name: /Investigation lanes/ });
    expect(lanes.querySelector("img")).toBeNull();
    expect(within(lanes).getAllByText(/<img src=x/).length).toBeGreaterThan(0);
  });
});

describe("Person timeline (ADR-0038 section 9)", () => {
  it("shows the forms of the name and rows by day, each opening its events", async () => {
    await openInvestigate("/investigate/people#user=alice");
    await userEvent.click(await screen.findByRole("tab", { name: "Timeline" }));
    const box = await screen.findByRole("region", { name: "Timeline" });
    expect(await within(box).findByText(/EXAMPLE\\alice, alice@example.com/)).toBeVisible();
    const days = within(box).getByRole("list", { name: "Activity by day" });
    expect(within(days).getAllByRole("heading", { level: 3 })).toHaveLength(2);
    const failed = within(box).getByRole("button", { name: "Failed to Office 365" });
    expect(failed).toHaveAttribute("title", "Open 2 events in Logs");
    await userEvent.click(failed);
    expect(await screen.findByText(/From alice > Timeline/)).toBeVisible();
  });

  it("is one page per person: identity, AI use, hosts, alerts, timeline (D197)", async () => {
    await openInvestigate("/investigate/people#user=alice");
    const tabs = await screen.findByRole("tablist", { name: "Person" });
    expect(
      within(tabs)
        .getAllByRole("tab")
        .map((t) => t.textContent),
    ).toEqual(["Identity and M365", "AI use", "Hosts and devices", "Alerts", "Timeline"]);
    // Identity and M365 holds the summary and the sign-ins, times local with UTC on hover
    // as Ask shows them, never the raw UTC string (review item 6).
    const signins = await screen.findByRole("region", { name: "Sign-ins" });
    expect(signins).toBeVisible();
    const at = await within(signins).findByText("Oct 30, 9:58:00 AM"); // tests run in UTC; log tables keep seconds
    expect(at.tagName).toBe("TIME");
    expect(at).toHaveAttribute("title", "2026-10-30 09:58 UTC");
    expect(within(signins).queryByText(/2026-10-30/)).toBeNull();
    await userEvent.click(within(tabs).getByRole("tab", { name: "Hosts and devices" }));
    const hosts = await screen.findByRole("region", { name: "Hosts and devices" });
    // The panels count whole days back from now and say so (owner, 2026-11-13).
    expect(within(hosts).getAllByText(/^Last 7 days/).length).toBeGreaterThanOrEqual(2);
    const table = within(hosts).getByRole("table", { name: "Hosts" });
    expect(within(table).getByRole("link", { name: "ws-0042" })).toBeVisible();
    expect(within(hosts).getByRole("table", { name: "Source addresses" })).toHaveTextContent("3");
    await userEvent.click(within(tabs).getByRole("tab", { name: "Alerts" }));
    expect(await screen.findByRole("region", { name: "Alerts" })).toBeVisible();
    await userEvent.click(within(tabs).getByRole("tab", { name: "Timeline" }));
    const box = await screen.findByRole("region", { name: "Timeline" });
    await userEvent.click(
      await within(box).findByRole("button", { name: "Sensitive data to AI: alice" }),
    );
    expect(window.location.pathname + window.location.hash).toBe("/alerts#item=a1");
  });
});

describe("A person's AI activity (D189)", () => {
  it("opens on its tab from a link that names it, with flags, sessions, and rollups", async () => {
    const spy = await openInvestigate(
      `/investigate/people#user=${encodeURIComponent("alice@example.com")}&tab=ai`,
    );
    const tab = await screen.findByRole("tab", { name: "AI use", selected: true });
    expect(tab).toBeVisible();
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
  async function open(analyst: boolean, refused = false) {
    window.history.replaceState(null, "", "/investigate/people#user=alice%40example.com&tab=ai");
    const spy = analyst
      ? mockApi("Codename", { mode: "login", signedIn: true, role: "analyst" })
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
    await screen.findByRole("heading", { level: 1, name: "People & devices" });
    return spy;
  }

  it("says what is needed and never asks the server", async () => {
    const spy = await open(true);
    expect(await screen.findByText(NEEDS)).toBeVisible();
    expect(screen.queryByRole("region", { name: "AI activity" })).toBeNull();
    expect(spy.mock.calls.some(([u]) => String(u).includes("/activity?"))).toBe(false);
  });

  it("still lists the person's alerts: the server leaves AI Watch items out", async () => {
    const spy = await open(true);
    const tabs = await screen.findByRole("tablist", { name: "Person" });
    await userEvent.click(within(tabs).getByRole("tab", { name: "Alerts" }));
    const box = await screen.findByRole("region", { name: "Alerts" });
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
