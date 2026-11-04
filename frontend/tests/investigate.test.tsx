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
  await screen.findByRole("heading", { level: 1, name: "Investigate" });
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
      "Open 0 expired in Search",
    );
    await userEvent.click(screen.getByRole("button", { name: /All entities/ }));
    expect(window.location.hash).toBe("");
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
      .map((h) => h.textContent);
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

  it("highlights a card's path and hands its events to Search", async () => {
    await openInvestigate("/investigate/people#user=root");
    const card = await screen.findByRole("button", { name: /Activities: Failed password/ });
    await userEvent.click(card);
    expect(card).toHaveAttribute("aria-pressed", "true");
    const other = screen.getByRole("button", { name: /Activities: Accepted publickey/ });
    expect(other.getAttribute("class")).toContain("opacity-40");
    const detail = screen.getByRole("region", { name: "Selected card" });
    expect(within(detail).getByText("Authentication")).toBeVisible();
    await userEvent.click(within(detail).getByRole("button", { name: "Open in Search" }));
    await screen.findByRole("heading", { level: 1, name: "Investigate" });
    expect(window.location.pathname).toBe("/investigate/search");
    // Search opens over the same range the investigation used (Last 7 days by default).
    expect(screen.getByLabelText("Time range")).toHaveValue("7d");
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
    expect(failed).toHaveAttribute("title", "Open 2 events in Search");
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
    // Identity and M365 holds the summary and the sign-ins.
    expect(await screen.findByRole("region", { name: "Sign-ins" })).toBeVisible();
    await userEvent.click(within(tabs).getByRole("tab", { name: "Hosts and devices" }));
    const hosts = await screen.findByRole("region", { name: "Hosts and devices" });
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
