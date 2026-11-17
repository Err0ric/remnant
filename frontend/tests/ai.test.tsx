import { QueryClient } from "@tanstack/react-query";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";
import { choose, optionLabels } from "./choose";

/** A rail area, then one of its tabs in the page header (ADR-0038). */
async function goTo(area: string, tab?: string) {
  const nav = screen.getByRole("navigation", { name: "Primary" });
  await userEvent.click(within(nav).getByRole("link", { name: area }));
  if (tab) {
    const tabs = await screen.findByRole("navigation", { name: `${area} tabs` });
    await userEvent.click(within(tabs).getByRole("link", { name: tab }));
  }
}

async function openAi(auth: MockAuth = { mode: "open" }) {
  window.history.replaceState(null, "", "/ai");
  return openAiAt(auth);
}

async function openAiAt(auth: MockAuth = { mode: "open" }) {
  const spy = mockApi("Codename", auth);
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
  await screen.findByRole("heading", { level: 1 });
  return spy;
}

afterEach(() => vi.restoreAllMocks());

/** The names-hidden line is a state notice in the card's body, never in its title row (D254). */
function namesHiddenInBody(card: HTMLElement) {
  const note = within(card)
    .getAllByRole("note")
    .find((n) => /^Names are hidden\. An admin can turn on/.test(n.textContent ?? ""));
  expect(note).toBeDefined();
  expect(note).toHaveAttribute("data-state-notice");
  expect(note).toBeVisible();
  const head = card.querySelector<HTMLElement>("[data-card-header]")!;
  expect(head).not.toContainElement(note!);
  expect(head).not.toHaveTextContent(/Names are hidden/);
}

describe("AI usage while it loads (owner, 2026-11-13)", () => {
  it.each([
    ["/ai", "AI services seen in network logs"],
    ["/ai/people", "Claude Code by person"],
    ["/agents/mcp", "MCP servers"],
  ])("holds the place with skeleton rows on %s, never an empty table", async (path, title) => {
    window.history.replaceState(null, "", path);
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    spy.mockImplementation(async (input, init) => {
      if (String(input).includes("/api/ai/usage")) await held;
      return base(input, init);
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);
    const card = await screen.findByRole("region", { name: title });
    const status = within(card).getByRole("status", { name: `Loading ${title}` });
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(within(card).queryByRole("table")).toBeNull();
    // The loaded card's shape: a column header row and two-line rows (D257).
    expect(status.querySelector("[data-skeleton-header]")).not.toBeNull();
    expect(status.querySelectorAll('[data-skeleton-row="tall"]')).toHaveLength(5);
    // The Needs attention line holds its place meanwhile.
    expect(screen.getByRole("status", { name: "Loading what needs attention" })).toBeVisible();
    expect(screen.queryByRole("region", { name: "Needs attention" })).toBeNull();
    release();
    expect(await within(card).findByRole("table")).toBeVisible();
    expect(within(card).queryByRole("status")).toBeNull();
    expect(await screen.findByRole("region", { name: "Needs attention" })).toBeVisible();
    expect(screen.queryByRole("status", { name: "Loading what needs attention" })).toBeNull();
  });
});

describe("AI usage when its request fails (D257)", () => {
  it("leaves no loading placeholder above the error", async () => {
    window.history.replaceState(null, "", "/ai");
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) =>
      String(input).includes("/api/ai/usage")
        ? new Response(JSON.stringify({ detail: "The lake is not readable" }), {
            status: 500,
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
    await screen.findByRole("heading", { level: 1 });
    const errors = await screen.findAllByRole("alert");
    expect(errors.length).toBeGreaterThan(0);
    expect(screen.queryByRole("status", { name: "Loading what needs attention" })).toBeNull();
    expect(document.querySelector('[aria-busy="true"]')).toBeNull();
    // No line claims that nothing needs attention when nothing could be read.
    expect(screen.queryByRole("region", { name: "Needs attention" })).toBeNull();
  });
});

describe("AI usage cost with no cost metrics (owner, 2026-11-08)", () => {
  it("says there is no cost data instead of 0.00", async () => {
    window.history.replaceState(null, "", "/ai");
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) => {
      const res = await base(input, init);
      if (!String(input).includes("/api/ai/usage")) return res;
      const body = await res.json();
      for (const p of body.people ?? [])
        if (p.person === "alice@example.com")
          Object.assign(p, { cost_usd: 0, tokens: 0, cost_reported: false });
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);
    await screen.findByRole("heading", { level: 1 });
    await goTo("AI usage", "People");
    const people = await screen.findByRole("region", { name: "Claude Code by person" });
    const row = within(people)
      .getByRole("link", { name: "alice@example.com" })
      .closest("tr") as HTMLElement;
    expect(within(row).getAllByText("None received")).toHaveLength(2);
    expect(within(row).queryByText("0.00")).toBeNull();
  });
});

describe("AI usage without View people in AI usage (D242)", () => {
  it("shows machines as text, with no person link, and says names are hidden", async () => {
    window.history.replaceState(null, "", "/ai");
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) => {
      const res = await base(input, init);
      if (!String(input).includes("/api/ai/usage")) return res;
      // What the server sends a viewer without the permission: two people on one machine.
      const body = await res.json();
      body.masked = true;
      for (const u of body.services) u.top_people = [];
      body.people.forEach((p: Record<string, unknown>, i: number) => {
        Object.assign(p, { person: i < 2 ? "ws-0042" : "Hidden", key: `row-${i}`, maybe: null });
        if (p.network) Object.assign(p.network, { who: "Hidden" });
      });
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);
    await screen.findByRole("heading", { level: 1 });
    const services = await screen.findByRole("region", {
      name: "AI services seen in network logs",
    });
    expect(within(services).queryByText("alice")).toBeNull();
    await goTo("AI usage", "People");
    const people = await screen.findByRole("region", { name: "Claude Code by person" });
    namesHiddenInBody(people);
    const rows = within(people).getAllByText("ws-0042");
    expect(rows).toHaveLength(2); // two people on one machine stay two rows
    for (const cell of rows) expect(cell.closest("a")).toBeNull();
    expect(within(people).queryByRole("link", { name: /ws-0042|Hidden/ })).toBeNull();
    expect(within(people).queryByText(/example\.com/)).toBeNull();
    expect(within(people).getByText(/Unmatched: not linked to a person/)).toBeVisible();
    expect(within(rows[0]!.closest("tr") as HTMLElement).getByText("12.50")).toBeVisible();
  });
});

describe("AI usage (ADR-0015)", () => {
  it("shows services with review status and lets an admin change it", async () => {
    const spy = await openAi();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    // A page with tabs is the current section in the rail; its open tab is the page (D268).
    expect(within(nav).getByRole("link", { name: "AI usage" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(await screen.findByText("1 service not approved in use")).toBeVisible();
    const table = screen.getByRole("region", { name: "AI services seen in network logs" });
    const row = within(table).getByText("ChatGPT").closest("tr") as HTMLElement;
    expect(within(row).getByText("Not approved")).toBeVisible();
    // Review opens under the row (list-detail), not inline in the table.
    await userEvent.click(within(row).getByRole("button", { name: "Review ChatGPT" }));
    const picker = within(table).getByLabelText("Review status of ChatGPT");
    expect(picker).toHaveValue("not_approved");
    await choose(picker, "approved");
    const put = spy.mock.calls.find(
      ([u, i]) => String(u).endsWith("/api/ai/services/chatgpt/status") && i?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ status: "approved" });
  });

  it("marks what is new and lists what is no longer seen against the previous period", async () => {
    await openAi();
    expect(await screen.findByText(/Against the previous 7 days:/)).toHaveTextContent(
      "Against the previous 7 days: 1 new, 1 no longer seen",
    );
    const table = screen.getByRole("region", { name: "AI services seen in network logs" });
    const chatgpt = within(table).getByText("ChatGPT").closest("tr") as HTMLElement;
    expect(within(chatgpt).getByText("New")).toBeVisible();
    const claude = within(table).getByText("Claude").closest("tr") as HTMLElement;
    expect(within(claude).queryByText("New")).toBeNull();
    const gone = screen.getByRole("region", { name: "No longer seen" });
    expect(within(gone).getByText("Copilot")).toBeVisible();
    expect(within(gone).getByText("Last seen Oct 1, 9:00 AM")).toBeVisible();
  });

  // AI usage counts its services only; Agents draws no AI usage comparison line at all
  // (fix list of 2026-11-16, item 14), so its MCP servers never reach that line.
  it.each([
    ["/ai", "Against the previous 7 days: 1 new, 1 no longer seen"],
    ["/agents/mcp", null],
  ])("counts on %s only what that area lists as new and no longer seen", async (path, said) => {
    window.history.replaceState(null, "", path);
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    // New and gone MCP servers beside the services: AI usage counts services, Agents MCP.
    spy.mockImplementation(async (input, init) => {
      const res = await base(input, init);
      if (!/\/api\/ai\/usage(\?|$)/.test(String(input))) return res;
      const body = (await res.json()) as Record<string, unknown>;
      const gone = (body.gone as unknown[]) ?? [];
      const mcp = (name: string) => ({
        kind: "mcp",
        id: name,
        name,
        status: "unreviewed",
        last_seen: "2026-10-01T09:00:00+00:00",
      });
      return new Response(
        JSON.stringify({
          ...body,
          new_mcp: ["github", "jira"],
          gone: [...gone, mcp("paste-share"), mcp("notes")],
        }),
        { headers: { "Content-Type": "application/json" } },
      );
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
    if (said) {
      expect(await screen.findByText(/Against the previous 7 days:/)).toHaveTextContent(said);
    } else {
      expect((await screen.findAllByText("paste-share")).length).toBeGreaterThan(0);
      expect(screen.queryByText(/Against the previous 7 days:/)).toBeNull();
    }
  });

  it("shows vendor ad tags apart and never as a service in use", async () => {
    await openAi();
    const table = await screen.findByRole("region", { name: "AI services seen in network logs" });
    expect(within(table).queryByText("OpenAI ad and measurement tags")).toBeNull();
    const apart = screen.getByRole("region", { name: "Not counted as AI use" });
    expect(within(apart).getByText("1 host group, 900 events")).toBeInTheDocument();
    expect(within(apart).getByText("bzr.openai.com, bzrcdn.openai.com")).toBeInTheDocument();
  });

  it("lists agents with what changed and sets a service's allowed data", async () => {
    const spy = await openAi();
    const table = await screen.findByRole("region", { name: "AI services seen in network logs" });
    const row = within(table).getByText("ChatGPT").closest("tr") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Review ChatGPT" }));
    await choose(within(table).getByLabelText("Allowed data for ChatGPT"), "internal");
    const put = spy.mock.calls.find(
      ([u, i]) => String(u).endsWith("/api/ai/services/chatgpt/data-level") && i?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ data_level: "internal" });
    await goTo("Agents", "Sessions");
    const agents = await screen.findByRole("table", { name: "Agents" });
    expect(
      within(agents).getByText("Claude Code, alice@example.com: ws-0042, ws-0043"),
    ).toBeVisible();
    // Each machine with its own events (D185).
    const machines = within(agents).getByRole("list", { name: /^Machines for / });
    expect(
      within(machines)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      expect.stringMatching(/^ws-0042: last seen .*, 40 in 24 h$/),
      expect.stringMatching(/^ws-0043: last seen .*, 2 in 24 h$/),
    ]);
    expect(within(agents).getByText("Changed")).toBeVisible();
    expect(within(agents).getByText("paste-share")).toBeVisible();
  });

  it("shows MCP servers and Claude usage with sensitive-data signals", async () => {
    await openAi();
    await goTo("Agents", "MCP servers");
    const mcp = await screen.findByRole("region", { name: "MCP servers" });
    expect(within(mcp).getByText("paste-share")).toBeVisible();
    expect(within(mcp).getByText("inventory, telemetry")).toBeVisible();
    await goTo("AI usage", "People");
    const people = await screen.findByRole("region", { name: "Claude Code by person" });
    const row = within(people)
      .getByRole("link", { name: "alice@example.com" })
      .closest("tr") as HTMLElement;
    expect(within(row).getByText("12.50")).toBeVisible();
    expect(within(row).getByText("1 signal")).toBeVisible();
    expect(within(row).getByText("Both")).toBeVisible();
  });

  it("says how each Claude user was seen, and counts network-only people (owner 2026-11-02)", async () => {
    await openAi();
    // The header counts plugin users (telemetry or hooks), not network-only people.
    expect(await screen.findByText(/2 Claude Code users/)).toBeVisible();
    const services = await screen.findByRole("region", {
      name: "AI services seen in network logs",
    });
    expect(
      within(services).getByText(
        "People: 1 seen only on the network, 1 only by the Claude Code plugin, 1 by both",
      ),
    ).toBeVisible();
    await goTo("AI usage", "People");
    const people = await screen.findByRole("region", { name: "Claude Code by person" });
    expect(within(people).getByText(/Seen on the network but no plugin: 1/)).toBeVisible();
    const erin = within(people)
      .getByRole("link", { name: "erin@example.com" })
      .closest("tr") as HTMLElement;
    // At least 22 characters wide, so an email never breaks inside a word (D257).
    expect(
      within(people).getByRole("link", { name: "erin@example.com" }).closest("td"),
    ).toHaveClass("min-w-[22ch]");
    expect(within(erin).getByText("Plugin")).toHaveAttribute(
      "title",
      "The hooks only: not seen on the network",
    );
    const dana = within(people)
      .getByRole("link", { name: "dana@example.com" })
      .closest("tr") as HTMLElement;
    expect(within(dana).getByText("Network")).toBeVisible();
    // D190: cost and tokens only from telemetry; network rows say what the network saw,
    // and a name that reads as a plugin person links to Identities, filled in.
    expect(within(erin).getAllByText("Not reported")).toHaveLength(2);
    expect(within(erin).queryByText("0.00")).toBeNull();
    // Each value in its own column, no sentence across them (fix list 22).
    const seen = within(dana).getByText("Network").closest("td") as HTMLElement;
    expect(seen).toHaveTextContent(/^NetworkClaude40 lookups, 2 devicesLast seen /);
    expect(dana.querySelector("td[colspan]")).toBeNull();
    expect(within(dana).getAllByText("Not reported")).toHaveLength(2);
    const name = within(dana).getByRole("link", { name: "dana@example.com" }).closest("td");
    expect(name).toHaveTextContent("Unmatched: may be dana.lee@example.com");
    const link = within(dana).getByRole("link", { name: "Link in Identities" });
    expect(link.getAttribute("href")).toMatch(/#alias=dlee&person=dana\.lee%40example\.com$/);
    const alice = within(people)
      .getByRole("link", { name: "alice@example.com" })
      .closest("tr") as HTMLElement;
    expect(within(alice).getByText("12.50")).toBeVisible(); // telemetry reports cost
  });

  it("opens Identities with the alias filled in", async () => {
    window.history.replaceState(null, "", "/identities#alias=dlee&person=dana.lee");
    mockApi("Codename", { mode: "open" });
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
    const form = await screen.findByRole("form", { name: "Add an alias" });
    expect(
      within(form)
        .getAllByRole("textbox")
        .map((i) => (i as HTMLInputElement).value),
    ).toEqual(["dlee", "dana.lee"]);
  });

  it("shows its tabs in the page header and keeps the open one in the path (ADR-0038)", async () => {
    await openAi();
    const tabs = screen.getByRole("navigation", { name: "AI usage tabs" });
    expect(within(tabs).getByRole("link", { name: "Services" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await userEvent.click(within(tabs).getByRole("link", { name: "People" }));
    expect(window.location.pathname).toBe("/ai/people");
    await goTo("Agents", "MCP servers");
    expect(window.location.pathname).toBe("/agents/mcp");
  });

  it("opens links from before the areas at their new address", async () => {
    window.history.replaceState(null, "", "/ai#mcp");
    await openAiAt();
    await screen.findByRole("region", { name: "MCP servers" });
    expect(window.location.pathname + window.location.hash).toBe("/agents/mcp");
  });

  it("gives analysts read-only status and no settings", async () => {
    await openAi({ mode: "login", signedIn: true, role: "analyst" });
    expect(await screen.findByText("Not approved")).toBeVisible();
    expect(screen.queryByLabelText("Review status of ChatGPT")).toBeNull();
    expect(screen.queryByRole("link", { name: "Review" })).toBeNull();
  });

  it("has no Review tab: reviewing is the Inventory, and the settings are under Settings", async () => {
    await openAi();
    const tabs = await screen.findByRole("navigation", { name: "AI usage tabs" });
    expect(
      within(tabs)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["Services", "People", "Inventory"]);
    const { canonical } = await import("@/lib/route");
    for (const [old, now] of [
      ["/ai/settings", "/ai/inventory"],
      ["/ai#settings", "/ai/inventory"],
      ["/ai/settings?from=mail", "/ai/inventory?from=mail"],
      ["/ai/watch", "/ai-settings"],
    ] as const) {
      window.history.replaceState(null, "", old);
      expect(canonical(), old).toBe(now);
    }
  });

  it("opens the Inventory from the old Review address: on All when nothing is unreviewed", async () => {
    // Nothing is unreviewed in the fixtures, so the Inventory's own rule opens it on All
    // with "0 to review" (the case with unreviewed items is tested with the Inventory).
    window.history.replaceState(null, "", "/ai/settings");
    await openAiAt();
    await waitFor(() =>
      expect(window.location.pathname + window.location.hash).toBe("/ai/inventory"),
    );
    const card = await screen.findByRole("region", { name: "AI inventory" });
    await within(card).findByText("ChatGPT");
    expect(within(card).getByRole("combobox", { name: "Status" })).toHaveValue("all");
    expect(document.querySelector("[data-header-count]")).toHaveTextContent(/^0 to review$/);
    expect(within(card).queryByText("Nothing matches these filters.")).toBeNull();
  });

  it("keeps the AI watch, MCP rules and catalog under Settings, for administrators", async () => {
    window.history.replaceState(null, "", "/ai-settings");
    await openAiAt();
    expect(
      await screen.findByRole("heading", { level: 1, name: "AI watch and catalog" }),
    ).toBeVisible();
    for (const name of ["AI watch", "MCP server rules", "AI service catalog"])
      expect(await screen.findByRole("region", { name })).toBeVisible();
    const settings = screen.getByRole("navigation", { name: "Settings" });
    expect(within(settings).getByRole("link", { name: "AI watch and catalog" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("does not open those settings for an analyst", async () => {
    window.history.replaceState(null, "", "/ai-settings");
    await openAiAt({ mode: "login", signedIn: true, role: "analyst" });
    await screen.findByRole("navigation", { name: "Primary" });
    expect(screen.queryByRole("region", { name: "AI watch" })).toBeNull();
    expect(screen.queryByRole("link", { name: "AI watch and catalog" })).toBeNull();
    // Told why, in place: never another page under this address.
    expect(
      await screen.findByRole("heading", { level: 1, name: "AI watch and catalog" }),
    ).toBeVisible();
    const box = screen.getByText("For administrators").closest("[data-empty]") as HTMLElement;
    expect(box).toHaveAttribute("data-empty", "restricted");
    expect(screen.queryByRole("button", { name: "Run" })).toBeNull();
  });

  it("saves the AI watch", async () => {
    window.history.replaceState(null, "", "/ai-settings");
    const spy = await openAiAt();
    const watch = await screen.findByRole("region", { name: "AI watch" });
    await userEvent.click(within(watch).getByLabelText("Watch for new AI use"));
    await userEvent.click(within(watch).getByRole("button", { name: "Save" }));
    const put = spy.mock.calls.find(
      ([u, i]) => String(u).endsWith("/api/ai/watch") && i?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toMatchObject({ enabled: true, sensitive: true });
  });
});

describe("A range too big for the memory share (F46)", () => {
  it("says so and shows the last 24 hours instead", async () => {
    const real = mockApi("Codename", { mode: "open" });
    const impl = real.getMockImplementation() as typeof fetch;
    real.mockRestore();
    window.history.replaceState(null, "", "/ai");
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation((url, init) => {
      const u = String(url);
      if (u.includes("/api/ai/usage")) {
        const start = new URL(u, "http://x").searchParams.get("start");
        if (start && Date.now() - Date.parse(start) > 2 * 86_400_000)
          return Promise.resolve(
            new Response(
              JSON.stringify({
                detail:
                  "Out of memory: this query needed more than the 819 MB it can use on this server. Try a shorter time range or fewer sources, or count and group instead of returning every row",
                code: "query_memory",
              }),
              { status: 503, headers: { "Content-Type": "application/json" } },
            ),
          );
      }
      return impl(url, init);
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Out of memory: this query needed more than the 819 MB");
    expect(alert).toHaveTextContent("Showing the last 24 hours instead.");
    const table = await screen.findByRole("region", { name: "AI services seen in network logs" });
    expect(within(table).getByText("ChatGPT")).toBeInTheDocument();
    expect(spy.mock.calls.filter(([u]) => String(u).includes("/api/ai/usage")).length).toBe(2);
  });
});

describe("Agent sessions from the hooks plugin (ADR-0026)", () => {
  it("lists sessions and opens one beside the list, in order, with its account", async () => {
    window.history.replaceState(null, "", "/ai#agents");
    mockApi("Codename", { mode: "open" });
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
    const card = await screen.findByRole("region", { name: "Agent sessions" });
    const list = await within(card).findByRole("list", { name: "Sessions" });
    await userEvent.click(within(list).getAllByRole("button", { name: /^dana@example\.com/ })[0]!);
    expect(window.location.hash).toMatch(/^#session=/);
    // Beside the list, not inside its card (list-detail, DESIGN.md 6.0).
    const detail = await screen.findByRole("region", { name: "Session detail" });
    expect(card.contains(detail)).toBe(false);
    expect(within(detail).getByRole("heading", { name: "Session on ws-0042" })).toBeVisible();
    // Execution by default: every step in order with its type from the server.
    const exec = await within(detail).findByRole("list", { name: "Session steps" });
    expect(
      within(exec)
        .getAllByRole("listitem")
        .map((r) => r.textContent?.replace(/^\d{1,2}:\d{2}:\d{2}\s[AP]M/, "")),
    ).toEqual([
      expect.stringMatching(/^Session started/),
      expect.stringMatching(/^Prompt42 chars/),
      expect.stringMatching(/^File accessRead \/home\/dana\/app\/auth\.py41 chars in, Flagged/),
      expect.stringMatching(/^Web or MCP accessMCP github create_issue13 chars in, Flagged/),
      expect.stringMatching(/^Turn end/),
    ]);
    // Conversation: by turn (D187): the prompt with what it led to, its calls, the end.
    await userEvent.click(within(detail).getByRole("button", { name: "Conversation" }));
    expect(window.location.hash).toMatch(/view=conversation/);
    const steps = await within(detail).findByRole("list", { name: "Session timeline" });
    const turn = within(steps).getByRole("list", { name: "Turn 1" });
    const rows = within(turn).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent?.replace(/^\d{1,2}:\d{2}:\d{2}\s[AP]M/, ""))).toEqual([
      expect.stringMatching(/^Prompt 2 tool calls: github 1, Read 142 chars/),
      expect.stringMatching(
        /^Read No result \(blocked, interrupted, or still running\) \/home\/dana\/app\/auth\.py/,
      ),
      expect.stringMatching(/^MCP No result .* github create_issue/),
      expect.stringMatching(/^Finished, 2 tool calls/),
    ]);
    expect(within(steps).getByText("Session started")).toBeVisible();
    expect(within(steps).queryByText(/Turn end/)).toBeNull();
    // Times in the viewer's zone, UTC on hover; Around shows on hover or focus only.
    const t = within(turn).getAllByRole("time")[0]!;
    expect(t.getAttribute("title")).toMatch(/ UTC$/);
    const around = within(turn).getAllByRole("button", { name: /^Around this step/ })[0]!;
    expect(around).toHaveClass("opacity-0", "group-hover:opacity-100", "focus:opacity-100");
    // Execution again: the default leaves the address.
    await userEvent.click(within(detail).getByRole("button", { name: "Execution" }));
    expect(window.location.hash).not.toMatch(/view=/);
  });

  it("hides empty sessions by default and names a quiet one ended (owner 2026-11-02)", async () => {
    window.history.replaceState(null, "", "/ai#agents");
    mockApi("Codename", { mode: "open" });
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
    const card = await screen.findByRole("region", { name: "Agent sessions" });
    const list = await within(card).findByRole("list", { name: "Sessions" });
    expect(within(list).queryByText("erin@example.com")).toBeNull();
    expect(within(card).getByText("(1 hidden)")).toBeVisible();
    await userEvent.click(
      within(card).getByRole("checkbox", { name: /Hide sessions with no tool calls or prompts/ }),
    );
    const erin = within(list).getByText("erin@example.com").closest("button") as HTMLElement;
    expect(erin).toHaveTextContent("ended (no end event), under a minute");
    expect(erin).toHaveTextContent("0 prompts, 0 calls, 0 files, 0 web domains");
  });
  it("shows each row's counts, top tools, and flags, and filters the list (D188)", async () => {
    window.history.replaceState(null, "", "/ai#agents");
    mockApi("Codename", { mode: "open" });
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
    const card = await screen.findByRole("region", { name: "Agent sessions" });
    const list = await within(card).findByRole("list", { name: "Sessions" });
    const dana = within(list).getByText("dana@example.com").closest("button") as HTMLElement;
    expect(dana).toHaveTextContent("ended, 4 min");
    expect(dana).toHaveTextContent("1 prompt, 2 calls, 1 file, 1 web domain");
    expect(dana).toHaveTextContent("Read, github");
    // An ended session with calls that never returned, and a first-seen MCP server.
    expect(within(dana).getByText("Blocked or failed call")).toBeVisible();
    expect(within(dana).getByText("New MCP server")).toBeVisible();
    const alice = within(list).getByText("alice@example.com").closest("button") as HTMLElement;
    expect(alice).toHaveTextContent("1 h 5 min");
    expect(within(alice).queryByText("Blocked or failed call")).toBeNull();
    // Nothing is open yet: one plain line, not a centered paragraph.
    expect(screen.getByText("Pick a session.").closest("[data-empty]")).toHaveAttribute(
      "data-empty",
      "default-empty",
    );
    const filters = within(card).getByRole("group", { name: "Filter sessions" });
    await choose(within(filters).getByRole("combobox", { name: "Tool" }), "Bash");
    expect(within(list).queryByText("dana@example.com")).toBeNull();
    expect(within(filters).getByText("1 of 2 sessions")).toBeVisible();
    // In the address, on the Sessions tab, and Reset clears it.
    expect(window.location.pathname + window.location.hash).toMatch(
      /^\/agents#(session=[^&]+&)?tool=Bash$/,
    );
    await userEvent.click(within(filters).getByRole("button", { name: "Reset" }));
    expect(within(filters).getByRole("combobox", { name: "Tool" })).toHaveValue("");
    expect(within(filters).queryByRole("button", { name: "Reset" })).toBeNull();
    expect(within(filters).getByText("2 sessions")).toBeVisible();
    await choose(within(filters).getByRole("combobox", { name: "Flags" }), "flagged");
    expect(within(list).queryByText("alice@example.com")).toBeNull();
    expect(within(list).getByText("dana@example.com")).toBeVisible();
    await choose(within(filters).getByRole("combobox", { name: "Machine" }), "ws-0311");
    expect(within(card).getByText("No sessions match these filters.")).toBeVisible();
    // The open session is the one in the address: Back undoes the filter and closes it.
    await userEvent.click(within(filters).getByRole("button", { name: "Reset" }));
    window.history.replaceState(null, "", "/agents/sessions");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await choose(within(filters).getByRole("combobox", { name: "Tool" }), "github");
    await userEvent.click(
      within(within(card).getByRole("list", { name: "Sessions" })).getByText("dana@example.com"),
    );
    expect(await screen.findByRole("region", { name: "Session detail" })).toBeVisible();
    expect(window.location.hash).toBe("#tool=github&session=s-77");
    window.history.back();
    await waitFor(() => expect(window.location.hash).toBe(""));
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Session detail" })).toBeNull(),
    );
    expect(within(filters).getByRole("combobox", { name: "Tool" })).toHaveValue("");
  });

  it("shows machines as text without View people in AI usage (D242)", async () => {
    window.history.replaceState(null, "", "/ai#agents");
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    // What the server sends a viewer without the permission.
    spy.mockImplementation(async (input, init) => {
      const res = await base(input, init);
      const url = String(input);
      if (!url.includes("/api/ai/sessions") && !url.includes("/api/agents/accounts")) return res;
      const body = await res.json();
      const mask = (s: Record<string, unknown>) =>
        Object.assign(s, {
          person: s.person ? (s.machine ?? "Hidden") : null,
          account: s.account ? (s.machine ?? "Hidden") : null,
          masked: true,
        });
      if (Array.isArray(body)) body.forEach(mask);
      else if (body.rows) {
        body.masked = true;
        body.rows.forEach((r: Record<string, unknown>, i: number) =>
          Object.assign(r, { email: "ws-0418", os_users: [], key: `row-${i}` }),
        );
      } else mask(body);
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
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
    const card = await screen.findByRole("region", { name: "Agent sessions" });
    const list = await within(card).findByRole("list", { name: "Sessions" });
    namesHiddenInBody(card);
    // No person filter: it would list machines as people.
    const filters = within(card).getByRole("group", { name: "Filter sessions" });
    // Hiding empty sessions is a filter: it sits in the filter bar, not the title row.
    expect(
      within(filters).getByRole("checkbox", {
        name: /Hide sessions with no tool calls or prompts/,
      }),
    ).toBeVisible();
    expect(within(filters).queryByRole("combobox", { name: "Person" })).toBeNull();
    expect(within(filters).getByRole("combobox", { name: "Machine" })).toBeVisible();
    // A person in the address filters nothing here and shows no Reset.
    const before = within(list).getAllByRole("button").length;
    window.history.replaceState(null, "", "/agents/sessions#person=alice@example.com");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(window.location.hash).toContain("person="));
    expect(within(list).getAllByRole("button")).toHaveLength(before);
    expect(within(filters).queryByRole("button", { name: "Reset" })).toBeNull();
    expect(within(list).queryByText(/example\.com/)).toBeNull();
    await userEvent.click(within(list).getAllByRole("button", { name: /^ws-0042/ })[0]!);
    const detail = await screen.findByRole("region", { name: "Session detail" });
    expect(within(detail).queryByRole("link", { name: /dana|Hidden/ })).toBeNull();
    // A machine is not looked up as an account: no other account's tier.
    expect(within(detail).getByText("Claude account hidden")).toBeVisible();
    // The numbers are the same; the person is the machine the server sent.
    const kpis = within(detail).getByRole("group", { name: "This session in numbers" });
    expect(kpis).toHaveTextContent(/Requests1.*Tool calls2/);
    expect(await within(detail).findByRole("img", { name: /^Session timeline:/ })).toBeVisible();
    expect(within(detail).queryByText(/example\.com/)).toBeNull();
  });
});

/** Agents > Sessions with one session open, the summary changed by `summary`. */
type Json = Record<string, unknown>;

interface Changes {
  summary?: Json;
  /** The steps answer's steps, changed. */
  steps?: (steps: Json[]) => Json[];
  /** Leave the session out of the list, as a sent link to a session the list does not show. */
  unlisted?: boolean;
}

/** Agents > Sessions with one session open, the answers changed by `changes`. */
async function openSession(changes: Changes = {}, hash = "session=s-77") {
  window.history.replaceState(null, "", `/agents/sessions#${hash}`);
  const spy = mockApi("Codename", { mode: "open" });
  const base = spy.getMockImplementation()!;
  const reply = (body: unknown) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  spy.mockImplementation(async (input, init) => {
    const res = await base(input, init);
    const url = String(input);
    if (url.includes("/s-77/summary")) return reply({ ...(await res.json()), ...changes.summary });
    if (url.includes("/s-77?") && changes.steps) {
      const body = await res.json();
      return reply({ ...body, steps: changes.steps(body.steps) });
    }
    if (url.includes("/api/ai/sessions?") && changes.unlisted)
      return reply((await res.json()).filter((r: Json) => r.session_id !== "s-77"));
    return res;
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
  const detail = await screen.findByRole("region", { name: "Session detail" });
  const kpis = within(detail).getByRole("group", { name: "This session in numbers" });
  await within(kpis).findByText("Requests");
  await waitFor(() => expect(kpis.querySelector("[aria-busy], [data-skeleton]")).toBeNull());
  return { detail, kpis, spy };
}

/** A step of s-77 at 18:00 plus `sec` seconds, every field empty. */
const stepAt = (sec: number) => ({
  time: new Date(Date.UTC(2026, 9, 22, 18, 0, sec)).toISOString(),
  role: null,
  tool: null,
  mcp_server: null,
  mcp_tool: null,
  path: null,
  web_host: null,
  program: null,
  prompt_chars: null,
  input_chars: null,
  output_chars: null,
});

const stepRows = (detail: HTMLElement) =>
  within(within(detail).getByRole("list", { name: "Session steps" }))
    .queryAllByRole("listitem")
    .map((r) => r.textContent ?? "");

const tile = (kpis: HTMLElement, label: string) =>
  kpis.querySelector(`[data-kpi="${label}"]`) as HTMLElement;

describe("Agents session detail (BACKLOG P1)", () => {
  it("shows the whole session's numbers, Not reported for tokens, zeros muted", async () => {
    const { detail, kpis, spy } = await openSession({ summary: { files: 0 } });
    await waitFor(() => expect(tile(kpis, "Requests")).toHaveTextContent("Requests1"));
    // The list reads its own days; the session's reads hold the whole session (30 days).
    const urls = spy.mock.calls.map(([u]) => String(u));
    expect(urls.some((u) => /\/api\/ai\/sessions\?days=90&start=[^&]+$/.test(u))).toBe(true);
    expect(urls.filter((u) => /\/s-77(\/summary)?\?days=30$/.test(u))).toHaveLength(2);
    // Blocked as the flags read it: no result in an ended session.
    expect(tile(kpis, "Tool calls")).toHaveTextContent("Tool calls22 failed or blocked");
    const tokens = within(tile(kpis, "Tokens")).getByText("Not reported");
    expect(tokens.parentElement).toHaveClass("text-text-muted");
    // Words on one line in the body size, never wrapped in the number font (fix list S2).
    expect(tokens).toHaveClass("whitespace-nowrap", "text-md", "font-normal");
    expect(within(tile(kpis, "Files")).getByText("0")).toHaveClass("text-text-muted");
    expect(tile(kpis, "Flags")).toHaveTextContent("Blocked or failed call, New MCP server");
    // Content: one line saying none is collected, and no way to open it.
    expect(
      within(detail).getByText("Content is not collected. Sizes and names only."),
    ).toBeVisible();
    expect(within(detail).getByRole("button", { name: "Show events in Logs" })).toBeVisible();
  });

  it("shows tokens in and out when telemetry reported them", async () => {
    const { kpis } = await openSession({
      summary: { tokens_in: 1500, tokens_out: 300, files_outside: 1 },
    });
    await waitFor(() => expect(tile(kpis, "Tokens")).toHaveTextContent("1,800In 1,500, out 300"));
    expect(tile(kpis, "Files")).toHaveTextContent("1 outside the folder");
  });

  it("shows flagged steps only, in the address, and says when the steps are cut", async () => {
    const { detail } = await openSession({ summary: { steps_cut: true, steps: 9000 } });
    expect(await within(detail).findByText(/Showing the first 5 of 9,000 steps/)).toBeVisible();
    await userEvent.click(within(detail).getByRole("button", { name: "Flagged only" }));
    expect(window.location.hash).toMatch(/show=flagged/);
    const rows = within(within(detail).getByRole("list", { name: "Session steps" })).getAllByRole(
      "listitem",
    );
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringMatching(/File access/),
      expect.stringMatching(/Web or MCP access/),
    ]);
    await userEvent.click(within(detail).getByRole("button", { name: "All" }));
    expect(window.location.hash).not.toMatch(/show=/);
  });

  it("goes back to the list on a narrow window, focus on the session's row", async () => {
    const { detail } = await openSession();
    const list = screen.getByRole("region", { name: "Agent sessions" });
    // The list gives way to the pane below 1024px; the Back link is for that width only.
    expect(list).toHaveClass("max-lg:hidden");
    const back = within(detail).getByRole("button", { name: "Back to sessions" });
    expect(back).toHaveClass("lg:hidden");
    await userEvent.click(back);
    await waitFor(() => expect(window.location.hash).not.toMatch(/session=/));
    expect(list).not.toHaveClass("max-lg:hidden");
    await waitFor(() =>
      expect(document.activeElement).toBe(list.querySelector('[data-session="s-77"]')),
    );
    // A row opens with Enter.
    await userEvent.keyboard("{Enter}");
    expect(window.location.hash).toMatch(/session=s-77/);
  });

  it("flags from the whole rule: failures, no result, new MCP servers, never bookkeeping", async () => {
    const failure = {
      time: "2026-10-22T18:00:10+00:00",
      event: "post_tool_use_failure",
      role: "tool_result",
      tool: "Read",
      mcp_server: null,
      mcp_tool: null,
      path: "/home/dana/app/auth.py",
      web_host: null,
      program: null,
      prompt_chars: null,
      input_chars: null,
      output_chars: null,
      event_id: "e3f",
      type: "tool_result",
    };
    const bookkeeping = { ...failure, event: "pre_tool_use", tool: "SubagentHandback" };
    const { detail } = await openSession({
      unlisted: true,
      summary: { new_mcp: [], failed: 1, unanswered: 1 },
      steps: (steps) => [
        ...steps.slice(0, 3),
        failure,
        {
          ...bookkeeping,
          time: "2026-10-22T18:02:00+00:00",
          event_id: "e9",
          type: "tool_call",
          counted: false,
        },
        ...steps.slice(3),
      ],
    });
    await userEvent.click(within(detail).getByRole("button", { name: "Flagged only" }));
    // The failed Read (call and result) and the MCP call with no result in an ended session;
    // the bookkeeping call with no result is not a call the server counts (D186).
    expect(stepRows(detail)).toEqual([
      expect.stringMatching(/^.*File accessRead \/home/),
      expect.stringMatching(/^.*Tool resultRead Failed/),
      expect.stringMatching(/^.*Web or MCP accessMCP github/),
    ]);
    // Conversation keeps the same steps, by turn.
    await userEvent.click(within(detail).getByRole("button", { name: "Conversation" }));
    const turn = within(detail).getByRole("list", { name: "Turn 1" });
    const rows = within(turn)
      .getAllByRole("listitem")
      .map((r) => r.textContent);
    expect(rows).toEqual([
      expect.stringMatching(/^.*Prompt 3 tool calls/),
      expect.stringMatching(/Read Failed/),
      expect.stringMatching(/MCP No result/),
      expect.stringMatching(/Finished, 3 tool calls, 1 failed$/),
    ]);
    expect(within(detail).queryByText("Session started")).toBeNull();
  });

  it("says when no step is flagged, with Show all", async () => {
    const { detail } = await openSession(
      { unlisted: true, summary: { new_mcp: [], state: "open" } },
      "session=s-77&show=flagged",
    );
    expect(await within(detail).findByText("No flagged steps in this session.")).toBeVisible();
    await userEvent.click(within(detail).getByRole("button", { name: "Show all" }));
    expect(window.location.hash).not.toMatch(/show=/);
  });

  it("on a cut list never flags a call whose result may be past the cut", async () => {
    // Cut before the turn ended: the calls' results may come after step 4.
    const cut = await openSession(
      {
        unlisted: true,
        summary: { new_mcp: [], steps_cut: true, steps: 9000 },
        steps: (steps) => steps.slice(0, 4),
      },
      "session=s-77&show=flagged",
    );
    expect(
      await within(cut.detail).findByText("None of the first 4 steps is flagged."),
    ).toBeVisible();
    expect(
      within(cut.detail).getByText(
        "The whole session has 2 failed or blocked calls, past the steps shown.",
      ),
    ).toBeVisible();
  });

  it("opens a sent link to a session the list does not show, with its own numbers", async () => {
    const { detail, kpis } = await openSession({ unlisted: true });
    expect(within(detail).getByRole("heading", { name: "Session on ws-0042" })).toBeVisible();
    await waitFor(() => expect(tile(kpis, "Flags")).toHaveTextContent("New MCP server"));
  });

  it("starts another session on its own defaults", async () => {
    const { detail } = await openSession({}, "session=s-77&view=conversation&show=flagged");
    expect(within(detail).getByRole("button", { name: "Conversation" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const list = screen.getByRole("list", { name: "Sessions" });
    await userEvent.click(within(list).getByText("alice@example.com"));
    expect(window.location.hash).toBe("#session=s-79");
  });

  it("opens the session's records in Logs with its window", async () => {
    const { detail } = await openSession();
    await userEvent.click(within(detail).getByRole("button", { name: "Show events in Logs" }));
    await waitFor(() => expect(window.location.pathname).toBe("/investigate/logs"));
    // A minute either side of the first and last records.
    const local = (iso: string) =>
      new Date(iso).toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    expect(
      await screen.findByText(
        `From Agents > Session on ws-0042, ${local("2026-10-22T17:59:00Z")} to ${local("2026-10-22T18:05:00Z")}`,
        { exact: false },
      ),
    ).toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: "SQL" }));
    await waitFor(() =>
      expect(document.body.textContent).toContain("template_id = 'claude_hooks'"),
    );
  });

  it("says flagged steps need the numbers when they did not load", async () => {
    window.history.replaceState(null, "", "/agents/sessions#session=s-77&show=flagged");
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) =>
      String(input).includes("/summary")
        ? new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })
        : base(input, init),
    );
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
    const detail = await screen.findByRole("region", { name: "Session detail" });
    expect(
      await within(detail).findByText(
        "Flagged steps could not be worked out: this session's numbers did not load.",
      ),
    ).toBeVisible();
    // The bar claims nothing about flags it cannot know: no segment says "not flagged".
    const drawn = await within(detail).findByRole("img", { name: /^Session timeline:/ });
    for (const el of drawn.querySelectorAll<HTMLElement>("[data-segment]")) {
      expect(el.getAttribute("title")).not.toMatch(/not flagged/);
    }
    const box = within(detail)
      .getByText("Flagged steps could not be worked out: this session's numbers did not load.")
      .closest("[data-empty]") as HTMLElement;
    expect(within(box).getByRole("button", { name: "Retry" })).toBeVisible();
  });

  it("draws the session as a bar of its steps, with a legend counted by the server", async () => {
    const { detail } = await openSession({
      summary: {
        types: { prompt: 3, tool_call: 0, tool_result: 7, file_access: 1, access: 1, other: 2 },
        failed: 1,
      },
    });
    const bar = await within(detail).findByRole("img", { name: /^Session timeline:/ });
    // One graphic with a spoken summary of the whole session's counts.
    expect(bar).toHaveAccessibleName(
      "Session timeline: 3 prompt, 0 tool call, 7 tool result, 1 file access, 1 web or MCP access, 2 other, 1 failed, 2 reached outside the session",
    );
    // One segment per step in order, colored by the server's type; other is an outline.
    expect(
      [...bar.querySelectorAll("[data-segment]")].map((s) => s.getAttribute("data-segment")),
    ).toEqual(["other", "prompt", "file_access", "access", "other"]);
    // Ice and graphite, the neutral for results; reaching outside the session is hatched.
    // Filled inline from the series variables, so the built CSS cannot leave a type empty.
    expect((bar.querySelector('[data-segment="prompt"]') as HTMLElement).style.background).toBe(
      "var(--series-ice)",
    );
    const file = bar.querySelector('[data-segment="file_access"]') as HTMLElement;
    expect(file).toHaveAttribute("data-hatched", "true");
    expect(file.style.background).toContain("var(--series-graphite)");
    expect(file.getAttribute("title")).toMatch(/reached outside the session/);
    const access = bar.querySelector('[data-segment="access"]') as HTMLElement;
    expect(access.style.background).toContain("var(--series-ice)");
    expect(bar.querySelector('[data-segment="prompt"]')).not.toHaveAttribute("data-hatched");
    expect(
      within(detail).getByText(
        "Hatched: a file access or a web or MCP access, the steps that reach outside the session.",
      ),
    ).toBeVisible();
    expect(bar.querySelector('[data-segment="other"]')).toHaveClass("border-text-muted");
    // Between the numbers and the View switch, as in the mock.
    const kpis = within(detail).getByRole("group", { name: "This session in numbers" });
    const view = within(detail).getByRole("group", { name: "View" });
    expect(kpis.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(bar.compareDocumentPosition(view) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The legend names every type with the whole session's count, and the failed mark; the
    // three kinds of tool call sit under one total, the Tool calls tile's number (fix list
    // S3: "Tool call 0" read beside "Tool calls 2").
    const legend = within(detail).getByRole("list", { name: "Step types" });
    expect([...legend.querySelectorAll(":scope > li")].map((li) => li.textContent)).toEqual([
      "Prompt3",
      "Tool result7",
      "Other2",
      "Failed1",
      "Tool calls 2:In the session0File access1Web or MCP access1",
    ]);
    const calls = legend.querySelector('[data-legend="tool_calls"]') as HTMLElement;
    const kinds = within(calls).getByRole("list", { name: "Tool calls by kind" });
    expect(within(kinds).getAllByRole("listitem")).toHaveLength(3);
    const tiles = within(detail).getByRole("group", { name: "This session in numbers" });
    expect(tile(tiles, "Tool calls")).toHaveTextContent(/^Tool calls2/);
    expect(calls.textContent).toMatch(/^Tool calls 2:/);
    // No tab stops of its own: the steps are reached in the list.
    expect(bar.querySelectorAll("[tabindex], button, a")).toHaveLength(0);
  });

  it("opens a segment's step below: scrolled to and focused", async () => {
    const { detail } = await openSession();
    const bar = await within(detail).findByRole("img", { name: /^Session timeline:/ });
    await userEvent.click(bar.querySelector('[data-segment="access"]')!);
    const row = document.activeElement as HTMLElement;
    expect(row.dataset.steps).toBe("e4");
    expect(row).toHaveTextContent(/Web or MCP accessMCP github/);
    expect(row).toHaveClass("bg-row-selected");
    // In Conversation the same step is its call row; the turn end is its own row.
    await userEvent.click(within(detail).getByRole("button", { name: "Conversation" }));
    await userEvent.click(bar.querySelectorAll('[data-segment="other"]')[1]!);
    expect(document.activeElement).toHaveTextContent(/^.*Finished, 2 tool calls/);
  });

  it("says the bar shows the loaded steps of a cut session, and dims what is not flagged", async () => {
    const { detail } = await openSession(
      { summary: { steps_cut: true, steps: 9000 } },
      "session=s-77&show=flagged",
    );
    const bar = await within(detail).findByRole("img", {
      name: /the bar shows the first 5 steps$/,
    });
    expect(
      within(detail).getByText(
        "The bar shows the first 5 steps; the counts are for the whole session.",
      ),
    ).toBeVisible();
    // Flagged only: the unanswered calls stay, the rest is dimmed.
    expect(bar.querySelector('[data-segment="prompt"]')).toHaveClass("opacity-25");
    expect(bar.querySelector('[data-segment="access"]')).not.toHaveClass("opacity-25");
  });

  it("opens a flagged step from a run whose first step is not flagged (Flagged only)", async () => {
    // Two parallel Bash calls; the one result goes to the first, so the second has none.
    const bash = (id: string, event: string, type: string, sec: number) => ({
      ...stepAt(sec),
      event,
      tool: "Bash",
      program: "git",
      event_id: id,
      type,
    });
    const { detail } = await openSession(
      {
        unlisted: true,
        summary: { new_mcp: [], unanswered: 1 },
        steps: (steps) => [
          steps[0]!,
          steps[1]!,
          bash("b1", "pre_tool_use", "tool_call", 20),
          bash("b2", "pre_tool_use", "tool_call", 21),
          bash("r1", "post_tool_use", "tool_result", 22),
          steps[4]!,
        ],
      },
      "session=s-77&show=flagged",
    );
    const bar = await within(detail).findByRole("img", { name: /^Session timeline:/ });
    const run = bar.querySelector('[data-segment="tool_call"]') as HTMLElement;
    expect(run).not.toHaveClass("opacity-25");
    expect(run).toHaveAttribute("data-opens", "b2");
    await userEvent.click(run);
    expect((document.activeElement as HTMLElement).dataset.steps).toBe("b2");
    // Everything else is dimmed, says why, and does nothing.
    const result = bar.querySelector('[data-segment="tool_result"]') as HTMLElement;
    expect(result).toHaveClass("opacity-25");
    expect(result.getAttribute("title")).toMatch(/\(not flagged\)$/);
    expect(result).not.toHaveAttribute("data-opens");
  });

  it("opens the flagged step of a slice in a long session (Flagged only)", async () => {
    const many = Array.from({ length: 1200 }, (_, i) => ({
      ...stepAt(i),
      event: i % 2 ? (i === 801 ? "post_tool_use_failure" : "post_tool_use") : "pre_tool_use",
      tool: "Bash",
      event_id: `x${i}`,
      type: i % 2 ? "tool_result" : "tool_call",
    }));
    const { detail } = await openSession(
      { unlisted: true, summary: { new_mcp: [], state: "open", failed: 1 }, steps: () => many },
      "session=s-77&show=flagged",
    );
    const bar = await within(detail).findByRole("img", { name: /^Session timeline:/ });
    const lit = [...bar.querySelectorAll<HTMLElement>("[data-segment]")].filter(
      (el) => !el.classList.contains("opacity-25"),
    );
    // A sliced bar leaves no gaps and sets no minimum widths, so it fits a phone-width pane.
    const row = bar.querySelector<HTMLElement>('[data-bar="segments"]')!;
    expect(row.className).toMatch(/overflow-hidden/);
    expect(row.className).not.toMatch(/gap-px/);
    expect(bar.querySelector(".min-w-px")).toBeNull();
    // Only the slices holding the failed call or its result are lit, each opening that step.
    expect(lit.map((el) => el.dataset.opens)).toEqual(
      lit.length === 1 ? ["x800"] : ["x800", "x801"],
    );
    for (const el of lit) {
      await userEvent.click(el);
      expect((document.activeElement as HTMLElement).dataset.steps).toBe(el.dataset.opens);
    }
  });

  it("never marks a failed bookkeeping call on the bar, as the server never counts it", async () => {
    const { detail } = await openSession({
      steps: (steps) => [
        ...steps.slice(0, 4),
        {
          ...stepAt(30),
          event: "post_tool_use_failure",
          tool: "SubagentHandback",
          event_id: "h1",
          type: "tool_result",
          counted: false,
        },
        steps[4]!,
      ],
    });
    const bar = await within(detail).findByRole("img", { name: /^Session timeline:/ });
    expect(bar.querySelector("[data-failed]")).toBeNull();
    expect(bar.getAttribute("aria-label")).not.toMatch(/failed/);
    const legend = within(detail).getByRole("list", { name: "Step types" });
    expect(within(legend).queryByText("Failed")).toBeNull();
  });

  it("opens the turn that follows a step Conversation does not list (a second session start)", async () => {
    const { detail } = await openSession({
      steps: (steps) => [
        steps[0]!,
        steps[1]!,
        { ...steps[0]!, time: "2026-10-22T18:00:07+00:00", event_id: "s2" },
        ...steps.slice(2),
      ],
    });
    await userEvent.click(within(detail).getByRole("button", { name: "Conversation" }));
    const bar = await within(detail).findByRole("img", { name: /^Session timeline:/ });
    const second = bar.querySelectorAll<HTMLElement>('[data-segment="other"]')[1]!;
    expect(second).toHaveAttribute("data-opens", "e3");
    await userEvent.click(second);
    expect((document.activeElement as HTMLElement).dataset.steps).toBe("e3");
  });

  it("draws a slice as its majority type and ticks it when any step reached outside", async () => {
    const many = Array.from({ length: 1200 }, (_, i) => ({
      ...stepAt(i),
      event: i % 2 ? "post_tool_use" : "pre_tool_use",
      tool: "Bash",
      event_id: `m${i}`,
      type: i === 3 ? "file_access" : i % 2 ? "tool_result" : "tool_call",
      ...(i === 3 ? { tool: "Read", path: "/home/dana/app/a.py" } : {}),
    }));
    const { detail } = await openSession({ unlisted: true, steps: () => many });
    const bar = await within(detail).findByRole("img", { name: /^Session timeline:/ });
    const segs = bar.querySelectorAll<HTMLElement>("[data-bar=segments] > span");
    const ticks = bar.querySelectorAll<HTMLElement>("[data-bar=ticks] > span");
    // The three rows line up: one cell per segment.
    expect(ticks).toHaveLength(segs.length);
    // Drawn exactly as the legend's Tool call (no hatch), and ticked below.
    const legendCall = within(detail)
      .getByRole("list", { name: "Step types" })
      .querySelector('[data-mark="tool_call"]') as HTMLElement;
    expect(segs[0]).toHaveAttribute("data-segment", "tool_call");
    expect(segs[0]!.style.background).toBe(legendCall.style.background);
    expect(segs[0]).not.toHaveAttribute("data-hatched");
    expect(ticks[0]).toHaveAttribute("data-tick", "true");
    expect(ticks[0]!.style.background).toBe("var(--text-secondary)");
    expect(segs[0]!.getAttribute("title")).toMatch(
      /; 1 of these steps reached outside the session$/,
    );
    // The next slice holds no outside step: no tick, nothing about outside on hover.
    expect(ticks[1]).not.toHaveAttribute("data-tick");
    expect(segs[1]!.getAttribute("title")).not.toMatch(/outside/);
    expect(
      within(detail).getByText(
        "Tick below: at least one step in this part of the bar reached outside the session (a file, the web, or an MCP server).",
      ),
    ).toBeVisible();
  });

  it("says the numbers did not load, with Retry, and no zeros", async () => {
    window.history.replaceState(null, "", "/agents/sessions#session=s-77");
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) =>
      String(input).includes("/summary")
        ? new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })
        : base(input, init),
    );
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
    const detail = await screen.findByRole("region", { name: "Session detail" });
    expect(await within(detail).findByText(/This session's numbers did not load/)).toBeVisible();
    expect(within(detail).getByRole("button", { name: "Retry Requests" })).toBeVisible();
    expect(within(detail).queryByText("Not reported")).toBeNull();
  });
});

describe("AI inventory (ADR-0038 section 7)", () => {
  it("lists every type, splits Active from Excluded, and excludes with a reason", async () => {
    window.history.replaceState(null, "", "/ai/inventory");
    const spy = mockApi("Codename", { mode: "open" });
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
    const card = await screen.findByRole("region", { name: "AI inventory" });
    await within(card).findByText("ChatGPT");
    expect(within(card).queryByText("Lab Notes App")).toBeNull();
    // One filter bar: State, Type, Status. Nothing is unreviewed here, so Status opens on
    // All and the header says "0 to review" (ADR-0052 section 3.3).
    const type = within(card).getByRole("combobox", { name: "Type" });
    expect(optionLabels(type)).toContain("MCP servers (1)");
    // Only types with items in the view: the one app is excluded, so it is not offered here.
    expect(optionLabels(type).some((o) => /^Microsoft 365 apps/.test(o))).toBe(false);
    expect(within(card).getByRole("combobox", { name: "Status" })).toHaveValue("all");
    expect(document.querySelector("[data-header-count]")).toHaveTextContent(/^0 to review$/);
    expect(within(card).queryByRole("button", { name: "Reset" })).toBeNull();
    await choose(within(card).getByRole("combobox", { name: "Status" }), "approved");
    expect(window.location.pathname + window.location.hash).toBe("/ai/inventory#status=approved");
    expect(within(card).queryByText("ChatGPT")).toBeNull();
    expect(within(card).getByText("1 of 2 items")).toBeVisible();
    await userEvent.click(within(card).getByRole("button", { name: "Reset" }));
    await within(card).findByText("ChatGPT");
    await userEvent.click(within(card).getByRole("button", { name: "Exclude github" }));
    const form = within(card).getByRole("form", { name: "Exclude github" });
    await userEvent.type(within(form).getByLabelText("Reason"), "IT's own server");
    await userEvent.click(within(form).getByRole("button", { name: "Exclude" }));
    expect(
      spy.mock.calls.some(
        ([u, init]) => String(u).includes("/api/ai/inventory/exclusions") && init?.method === "PUT",
      ),
    ).toBe(true);
    await userEvent.click(within(card).getByRole("button", { name: /^Excluded/ }));
    const row = (await within(card).findByText("Lab Notes App")).closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("Pilot app");
    // Group by sits in the filter bar, not in the card's title row (D254); the exports are
    // the page header's two secondary buttons (one filter row, owner 2026-11-16).
    const bar = within(card).getByRole("group", { name: "Filter the inventory" });
    const actions = document.querySelector<HTMLElement>("[data-header-actions]")!;
    expect(within(actions).getByRole("button", { name: /^Export CSV/ })).toBeVisible();
    expect(within(actions).getByRole("button", { name: /^Export JSON/ })).toBeVisible();
    expect(within(bar).queryByRole("button", { name: /^Export/ })).toBeNull();
    // One excluded item makes one group whatever the grouping: no Group by there.
    expect(within(bar).queryByLabelText("Group by")).toBeNull();
    await userEvent.click(within(card).getByRole("button", { name: /^Active/ }));
    expect(await within(bar).findByLabelText("Group by")).toBeVisible();
    const head = card.querySelector<HTMLElement>("[data-card-header]")!;
    expect(within(head).queryByRole("button")).toBeNull();
    expect(within(head).queryByRole("combobox")).toBeNull();
  });

  async function openInventory(role: "admin" | "analyst") {
    window.history.replaceState(null, "", "/ai/inventory");
    const spy = mockApi("Codename", { mode: "login", signedIn: true, role });
    const base = spy.getMockImplementation() as typeof fetch;
    // One service still to review, beside the approved MCP server.
    spy.mockImplementation(async (input, init) => {
      const res = await base(input, init);
      if (!/\/api\/ai\/inventory\?/.test(String(input))) return res;
      const body = await res.json();
      body.items[0].status = "unreviewed";
      body.to_review = 1; // the server counts it
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
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
    const card = await screen.findByRole("region", { name: "AI inventory" });
    await within(card).findByText("ChatGPT");
    return { spy, card };
  }

  it("opens on Unreviewed when something waits, and an admin reviews it in place", async () => {
    const { spy, card } = await openInventory("admin");
    expect(within(card).getByRole("combobox", { name: "Status" })).toHaveValue("unreviewed");
    expect(document.querySelector("[data-header-count]")).toHaveTextContent(/^1 to review$/);
    // The usual view: a clean address and no Reset. The approved server is under All.
    expect(window.location.hash).toBe("");
    expect(within(card).queryByRole("button", { name: "Reset" })).toBeNull();
    expect(within(card).queryByText("github")).toBeNull();
    await choose(
      within(card).getByRole("combobox", { name: "Review status of ChatGPT" }),
      "approved",
    );
    const sent = spy.mock.calls.find(
      ([u, init]) =>
        String(u).endsWith("/api/ai/services/chatgpt/status") && init?.method === "PUT",
    );
    expect(JSON.parse(String(sent?.[1]?.body))).toEqual({ status: "approved" });
    // The Excluded view is out of review: it lists everything excluded, whatever the default.
    await userEvent.click(within(card).getByRole("button", { name: /^Excluded/ }));
    const excluded = (await within(card).findByText("Lab Notes App")).closest("tr") as HTMLElement;
    expect(within(card).getByRole("combobox", { name: "Status" })).toHaveValue("all");
    expect(within(excluded).queryByRole("combobox")).toBeNull();
    await userEvent.click(within(card).getByRole("button", { name: /^Active/ }));
    expect(within(card).getByRole("combobox", { name: "Status" })).toHaveValue("unreviewed");
    // An MCP server is reviewed through its rule; Unreviewed clears the rule.
    await choose(within(card).getByRole("combobox", { name: "Status" }), "all");
    await choose(
      within(card).getByRole("combobox", { name: "Review status of github" }),
      "not_approved",
    );
    const rule = spy.mock.calls.find(
      ([u, init]) => String(u).endsWith("/api/ai/mcp-rules") && init?.method === "PUT",
    );
    expect(JSON.parse(String(rule?.[1]?.body))).toEqual({
      pattern: "github",
      status: "not_approved",
    });
    await userEvent.click(within(card).getByRole("button", { name: "Reset" }));
    // The export is the view: it carries the Status filter.
    await userEvent.click(screen.getByRole("button", { name: /^Export CSV/ }));
    expect(
      spy.mock.calls.some(([u]) => /inventory\/export\?.*status=unreviewed/.test(String(u))),
    ).toBe(true);
  });

  it("says so when a review is not saved", async () => {
    const { spy, card } = await openInventory("admin");
    const base = spy.getMockImplementation() as typeof fetch;
    spy.mockImplementation(async (input, init) =>
      String(input).endsWith("/api/ai/services/chatgpt/status")
        ? new Response(JSON.stringify({ error: { code: "internal", message: "It broke" } }), {
            status: 500,
            headers: { "content-type": "application/json" },
          })
        : base(input, init),
    );
    await choose(
      within(card).getByRole("combobox", { name: "Review status of ChatGPT" }),
      "approved",
    );
    expect(await within(card).findByRole("alert")).toHaveTextContent(
      /^The review status was not saved: /,
    );
  });

  it("shows the status as text to an analyst: review stays with admins", async () => {
    const { card } = await openInventory("analyst");
    expect(within(card).getByRole("combobox", { name: "Status" })).toHaveValue("unreviewed");
    expect(within(card).queryByRole("combobox", { name: /^Review status of/ })).toBeNull();
    const row = within(card).getByText("ChatGPT").closest("tr") as HTMLElement;
    expect(within(row).getByText("Unreviewed")).toBeVisible();
  });
});

describe("Agents overview and tools (ADR-0038 section 6)", () => {
  async function openAt(path: string) {
    window.history.replaceState(null, "", path);
    mockApi("Codename", { mode: "open" });
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

  it("opens on Overview with every number opening Search", async () => {
    await openAt("/agents");
    const box = await screen.findByRole("region", { name: "Overview" });
    const kpi = await within(box).findByText("Failed tool calls");
    const card = kpi.closest("[data-kpi]") as HTMLElement;
    expect(within(card).getByRole("button", { name: /^Failed tool calls: 7\./ })).toBeVisible();
    expect(within(box).getByRole("note")).toHaveTextContent("ws-0420");
    await userEvent.click(within(card).getByRole("button", { name: /^Failed tool calls: 7\./ }));
    expect(window.location.pathname).toBe("/investigate/logs");
  });

  it("has three tabs, the numbers as a strip on Sessions, and no filled button there", async () => {
    await openAt("/agents");
    const tabs = await screen.findByRole("navigation", { name: "Agents tabs" });
    expect(
      within(tabs)
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["Sessions", "MCP servers", "Accounts"]);
    expect(within(tabs).getByRole("link", { name: "Sessions" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // The strip that was the Overview tab, above the sessions.
    const strip = await screen.findByRole("region", { name: "Overview" });
    const sessions = await screen.findByRole("region", { name: "Agent sessions" });
    expect(strip.compareDocumentPosition(sessions) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(document.querySelector("[data-primary]")).toBeNull();
  });

  it("counts the strip for the time chosen, exactly, and says so (PR 639 review)", async () => {
    window.history.replaceState(null, "", "/agents");
    const spy = mockApi("Codename", { mode: "open" });
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
    // How far back the last read of a path starts, in minutes.
    const back = (path: string) => {
      const u = spy.mock.calls
        .map(([x]) => String(x))
        .filter((x) => x.includes(path))
        .at(-1);
      const start = u ? new URL(u, "http://x").searchParams.get("start") : null;
      return start ? Math.round((Date.now() - Date.parse(start)) / 60_000) : null;
    };
    const strip = await screen.findByRole("region", { name: "Overview" });
    expect(back("/api/agents/overview")).toBe(7 * 1440);
    // On the strip and on the sessions list under it.
    expect(screen.getAllByText(/^Last 7 days\./).length).toBeGreaterThanOrEqual(1);
    expect(
      await within(await screen.findByRole("region", { name: "Agent sessions" })).findByText(
        /^Last 7 days, from the hooks plugin$/,
      ),
    ).toBeVisible();
    // The note about devices that sent nothing, and a number opening its rows in Logs.
    expect(within(strip).getByRole("note")).toHaveTextContent("ws-0420");
    const time = screen.getByRole("group", { name: "Time" });
    await userEvent.click(within(time).getByRole("button", { name: "30 days" }));
    await waitFor(() => expect(back("/api/agents/overview")).toBe(30 * 1440));
    expect((await screen.findAllByText(/^Last 30 days\./)).length).toBeGreaterThanOrEqual(1);
    // 1 hour is an hour, in the reads and in the words, and the list reads the same hour.
    await userEvent.click(within(time).getByRole("button", { name: "1 hour" }));
    await waitFor(() => expect(back("/api/agents/overview")).toBe(60));
    expect((await screen.findAllByText(/^Last hour\./)).length).toBeGreaterThanOrEqual(1);
    await waitFor(() => expect(back("/api/ai/sessions?")).toBe(60));
    const card = (await screen.findByText("Failed tool calls")).closest(
      "[data-kpi]",
    ) as HTMLElement;
    await userEvent.click(within(card).getByRole("button", { name: /^Failed tool calls: 7\./ }));
    expect(window.location.pathname).toBe("/investigate/logs");
  });

  it("says there are no MCP servers only when no built-in tool was called either", async () => {
    const open = async (tools: unknown[]) => {
      window.history.replaceState(null, "", "/agents/mcp");
      const spy = mockApi("Codename", { mode: "open" });
      const real = spy.getMockImplementation() as typeof fetch;
      spy.mockImplementation(async (url, init) => {
        const res = await real(url, init);
        const u = String(url);
        if (!u.includes("/api/agents/overview") && !u.includes("/api/ai/usage")) return res;
        const body = await res.json();
        const next = u.includes("/api/ai/usage") ? { ...body, mcp: [] } : { ...body, tools };
        return new Response(JSON.stringify(next), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      });
      vi.resetModules();
      const { loadBranding } = await import("@/lib/branding");
      await loadBranding();
      const { App } = await import("@/app/App");
      return render(
        <App
          initialTheme="dark"
          queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
        />,
      );
    };
    const first = await open([]);
    const card = await screen.findByRole("region", { name: "MCP servers" });
    expect(await within(card).findByText("No MCP servers yet.")).toBeVisible();
    expect(within(card).queryByRole("button", { name: "Tools of Built-in" })).toBeNull();
    first.unmount();
    vi.restoreAllMocks();
    // With built-in calls and no server, the table has the one group row.
    await open([
      {
        tool: "Bash",
        mcp: false,
        status: "built_in",
        people: 1,
        devices: 1,
        calls: 4,
        failed: 0,
        first_seen: null,
        last_seen: null,
        drill: "SELECT 1",
      },
    ]);
    const again = await screen.findByRole("region", { name: "MCP servers" });
    expect(await within(again).findByRole("button", { name: "Tools of Built-in" })).toBeVisible();
    expect(within(again).queryByText("No MCP servers yet.")).toBeNull();
  });

  it("says so in the row when the tool figures cannot be read, and keeps the Built-in row", async () => {
    window.history.replaceState(null, "", "/agents/mcp");
    const spy = mockApi("Codename", { mode: "open" });
    const real = spy.getMockImplementation() as typeof fetch;
    spy.mockImplementation(async (url, init) =>
      String(url).includes("/api/agents/overview")
        ? new Response(JSON.stringify({ error: { code: "internal", message: "It broke" } }), {
            status: 500,
            headers: { "content-type": "application/json" },
          })
        : real(url, init),
    );
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
    const card = await screen.findByRole("region", { name: "MCP servers" });
    const toggle = await within(card).findByRole("button", { name: "Tools of Built-in" });
    await userEvent.click(toggle);
    expect(await within(card).findByRole("alert")).toHaveTextContent(
      /^Built-in tools did not load: /,
    );
    expect(within(card).queryByText(/^No tool calls/)).toBeNull();
    // Still there to close.
    await userEvent.click(toggle);
    expect(within(card).queryByRole("alert")).toBeNull();
  });

  it("shows a server's tools under its row, and the built-in tools under one group row", async () => {
    await openAt("/agents/tools");
    // The old Tools address opens MCP servers.
    await waitFor(() => expect(window.location.pathname).toBe("/agents/mcp"));
    const card = await screen.findByRole("region", { name: "MCP servers" });
    await userEvent.click(
      await within(card).findByRole("button", { name: "Calls and failures of paste-share" }),
    );
    const own = await within(card).findByRole("table", {
      name: "Calls and failures of paste-share",
    });
    const row = within(own).getByText("paste-share").closest("tr") as HTMLElement;
    expect(within(row).getByText("MCP server")).toBeVisible();
    expect(within(row).getByText("Not approved")).toBeVisible();
    expect(within(own).queryByText("Bash")).toBeNull();
    // One group row for the tools that belong to no server.
    const group = card.querySelector('tr[data-row="built-in"]') as HTMLElement;
    expect(group).toHaveTextContent(/^Built-in\d+ tools? of Claude Code itself/);
    const toggle = within(group).getByRole("button", { name: "Tools of Built-in" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    // One row open at a time: the server's tools close.
    expect(
      within(card).queryByRole("table", { name: "Calls and failures of paste-share" }),
    ).toBeNull();
    const builtIn = await within(card).findByRole("table", { name: "Built-in tools" });
    // The tool rows say the days they count, and so does the sessions list.
    expect(within(card).getByText("Last 7 days.")).toBeVisible();
    const bash = within(builtIn).getByText("Bash").closest("tr") as HTMLElement;
    expect(within(bash).getByText("Built in")).toBeVisible();
    expect(within(builtIn).queryByText("paste-share")).toBeNull();
  });

  it.each([
    ["/agents/overview", "/agents"],
    ["/agents/sessions", "/agents"],
    ["/agents/tools", "/agents/mcp"],
    ["/agents#tools", "/agents/mcp"],
    ["/agents#overview", "/agents"],
    ["/agents/tools?from=mail", "/agents/mcp?from=mail"],
  ])("sends the old address %s to %s", async (old, now) => {
    const { canonical } = await import("@/lib/route");
    window.history.replaceState(null, "", old);
    expect(canonical()).toBe(now);
  });

  it("sends an old session link to the Sessions tab", async () => {
    await openAt("/agents#session=s-77");
    await screen.findByRole("region", { name: "Agent sessions" });
  });
});

describe("Claude accounts (ADR-0030 amendment)", () => {
  it("lists accounts by tier with their evidence", async () => {
    window.history.replaceState(null, "", "/agents/accounts");
    mockApi("Codename", { mode: "open" });
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
    const card = await screen.findByRole("region", { name: "Claude accounts" });
    const tiers = await within(card).findByRole("list", { name: "Accounts by tier" });
    expect(tiers).toHaveTextContent("Company, confirmed1");
    expect(tiers).toHaveTextContent("Personal1");
    expect(within(card).getByText("mail.test is not an organization domain")).toBeVisible();
    expect(within(card).getAllByText("Personal")[1]).toHaveAttribute(
      "title",
      "Personal Claude account",
    );
  });

  it("shows devices as text without View people in AI usage (D242)", async () => {
    window.history.replaceState(null, "", "/agents/accounts");
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) => {
      const res = await base(input, init);
      if (!String(input).includes("/api/agents/accounts")) return res;
      const body = await res.json();
      body.masked = true;
      body.rows.forEach((r: Record<string, unknown>, i: number) =>
        Object.assign(r, { email: "ws-0418", os_users: [], key: `row-${i}` }),
      );
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
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
    const card = await screen.findByRole("region", { name: "Claude accounts" });
    await within(card).findByText(/Names are hidden\. An admin can turn on/);
    namesHiddenInBody(card);
    const rows = within(card).getAllByRole("row").slice(1);
    expect(rows.length).toBeGreaterThan(1); // two accounts on one device stay two rows
    for (const row of rows) {
      const cell = within(row).getAllByRole("cell")[0]!;
      expect(cell).toHaveTextContent(/^ws-0418/);
      expect(within(cell).queryByRole("link")).toBeNull();
    }
    expect(within(card).queryByText(/dana/)).toBeNull();
    expect(within(card).getByRole("list", { name: "Accounts by tier" })).toHaveTextContent(
      "Personal1",
    );
  });
});

describe("Agents and the inventory without View people in AI usage (D242)", () => {
  /** What the server sends a viewer without the permission. */
  function masked(spy: ReturnType<typeof mockApi>) {
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) => {
      const res = await base(input, init);
      const url = String(input);
      const agents = url.endsWith("/api/ai/agents");
      if (!agents && !/\/api\/ai\/inventory\?/.test(url)) return res;
      const body = await res.json();
      if (agents)
        body.forEach((a: Record<string, unknown>, i: number) =>
          Object.assign(
            a,
            { owners: [], masked: true },
            a.kind === "Claude Code" ? { agent: `cc|row-${i}`, label: "Claude Code: ws-0042" } : {},
          ),
        );
      else body.masked = true;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
  }

  it("shows agents by machine with no owner links", async () => {
    window.history.replaceState(null, "", "/ai");
    const spy = mockApi("Codename", { mode: "open" });
    masked(spy);
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
    await screen.findByRole("heading", { level: 1 });
    await goTo("Agents", "Sessions");
    const table = await screen.findByRole("table", { name: "Agents" });
    expect(within(table).getByText("Claude Code: ws-0042")).toBeVisible();
    expect(within(table).queryByText(/alice/)).toBeNull();
    expect(within(table).queryByRole("link", { name: /example\.com/ })).toBeNull();
    const card = screen.getByRole("region", { name: "Agents" });
    namesHiddenInBody(card);
  });

  it("says names are hidden on the inventory", async () => {
    window.history.replaceState(null, "", "/ai/inventory");
    const spy = mockApi("Codename", { mode: "open" });
    masked(spy);
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
    const card = await screen.findByRole("region", { name: "AI inventory" });
    await within(card).findByText("ChatGPT");
    namesHiddenInBody(card);
  });
});

describe("AI usage: the time filter (ADR-0052 section 3.7; owner, 2026-11-13)", () => {
  const asked = (spy: ReturnType<typeof mockApi>) =>
    spy.mock.calls
      .map(([u]) => new URL(String(u), "http://x"))
      .filter((u) => u.pathname === "/api/ai/usage");

  it("has the five choices in the address, and Custom asks with a start and an end", async () => {
    const spy = await openAi();
    const time = await screen.findByRole("group", { name: "Time" });
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
    // The default is not in the address and shows no Reset; another choice is, and does.
    expect(window.location.hash).toBe("");
    expect(screen.queryByRole("button", { name: "Reset" })).toBeNull();
    await userEvent.click(within(time).getByRole("button", { name: "30 days" }));
    expect(window.location.hash).toBe("#time=30d");
    expect(screen.getByRole("button", { name: "Reset" })).toBeVisible();
    await waitFor(() => {
      const start = Date.parse(String(asked(spy).at(-1)?.searchParams.get("start")));
      expect(Date.now() - start).toBeGreaterThan(29.9 * 86_400_000);
    });
    expect(asked(spy).at(-1)?.searchParams.get("end")).toBeNull();

    await userEvent.click(within(time).getByRole("button", { name: "Custom" }));
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-11-01T08:00" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-11-02T08:00" } });
    // This endpoint reads bounds to the minute with an inclusive end, so the end sent is
    // the start of the next minute: the minute "To" names is kept.
    await waitFor(() =>
      expect(asked(spy).at(-1)?.searchParams.get("end")).toBe(
        new Date("2026-11-02T08:01").toISOString(),
      ),
    );
    const frag = new URLSearchParams(window.location.hash.slice(1));
    expect(frag.get("time")).toBe("custom");
    expect(frag.get("from")).toBe(new Date("2026-11-01T08:00").toISOString());
    // The comparison is against the period of the same length before.
    expect((await screen.findAllByText(/period of the same length before/)).length).toBeGreaterThan(
      0,
    );
    await userEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(window.location.hash).toBe("");
  });

  it("opens on the time an address names, and keeps it across the page's tabs", async () => {
    window.history.replaceState(null, "", "/ai#time=24h");
    await openAiAt();
    const pressed = async () =>
      within(await screen.findByRole("group", { name: "Time" })).getByRole("button", {
        name: "24 hours",
      });
    expect(await pressed()).toHaveAttribute("aria-pressed", "true");
    const tabs = screen.getByRole("navigation", { name: "AI usage tabs" });
    const people = within(tabs).getByRole("link", { name: "People" });
    expect(people).toHaveAttribute("href", "/ai/people#time=24h");
    await userEvent.click(people);
    expect(window.location.pathname + window.location.hash).toBe("/ai/people#time=24h");
    expect(await pressed()).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(within(tabs).getByRole("link", { name: "Services" }));
    expect(window.location.pathname + window.location.hash).toBe("/ai#time=24h");
    expect(await pressed()).toHaveAttribute("aria-pressed", "true");
    // With the usual time, a tab link has no fragment.
    await userEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(within(tabs).getByRole("link", { name: "People" })).toHaveAttribute(
      "href",
      "/ai/people",
    );
  });
});

describe("Agents header (fix list item 14)", () => {
  it("counts the page's own sessions, people, and tool calls, as the tiles do", async () => {
    window.history.replaceState(null, "", "/agents/sessions");
    const spy = await openAiAt();
    const strip = await screen.findByRole("region", { name: "Overview" });
    await waitFor(() =>
      expect(document.querySelector("[data-header-count]")).toHaveTextContent(
        /^12 sessions · 3 people · 240 tool calls$/,
      ),
    );
    // The same numbers as the tiles beside them.
    expect(strip.querySelector('[data-kpi="Sessions"]')).toHaveTextContent(/12/);
    expect(strip.querySelector('[data-kpi="People"]')).toHaveTextContent(/3/);
    expect(strip.querySelector('[data-kpi="Tool calls"]')).toHaveTextContent(/240/);
    // One comparison line: the strip's, never AI usage's line about services as well.
    expect(screen.getAllByText(/Changes against|Comparisons start|No comparison yet/)).toHaveLength(
      1,
    );
    expect(screen.queryByText(/no longer seen|Nothing earlier to compare/)).toBeNull();
    // Needs attention names the strip's own not-approved MCP server (fix list item 15):
    // Sessions never asks for the whole AI usage answer, the page's heaviest read.
    const attention = await screen.findByRole("region", { name: "Needs attention" });
    expect(attention).toHaveTextContent("1 not approved MCP server in use");
    expect(spy.mock.calls.some(([u]) => String(u).includes("/api/ai/usage"))).toBe(false);
    await goTo("Agents", "MCP servers");
    await screen.findByRole("region", { name: "MCP servers" });
    expect(spy.mock.calls.some(([u]) => String(u).includes("/api/ai/usage"))).toBe(true);
  });
});

describe("Agents Sessions and Accounts (PR 639)", () => {
  it("says how the list adds up to the Sessions tile", async () => {
    window.history.replaceState(null, "", "/agents/sessions");
    await openAiAt();
    const card = await screen.findByRole("region", { name: "Agent sessions" });
    const line = await within(card).findByText(/in the Sessions tile/);
    expect(line).toHaveTextContent(
      "12 sessions in the Sessions tile: 2 with step detail · 1 empty, hidden · 9 seen only in Claude Code telemetry",
    );
    // The parts add up to the tile, and the step-detail part is the list's own count.
    const nums = [
      ...(line.textContent ?? "").matchAll(/(\d+) (?:with step detail|empty|seen)/g),
    ].map((m) => Number(m[1]));
    expect(nums.reduce((a, b) => a + b, 0)).toBe(12);
    expect(within(card).getByText("2 sessions")).toBeVisible();
    await userEvent.click(
      within(card).getByRole("checkbox", { name: /Hide sessions with no tool calls or prompts/ }),
    );
    expect(line).toHaveTextContent(
      "12 sessions in the Sessions tile: 2 with step detail · 1 empty · 9 seen only in Claude Code telemetry",
    );
    expect(within(card).getByText("3 sessions")).toBeVisible();
  });

  it("says when the list holds only the newest of more sessions (the cap of 100)", async () => {
    window.history.replaceState(null, "", "/agents/sessions");
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    const one = (i: number) => ({
      session_id: `c-${i}`,
      person: "erin@example.com",
      machine: "ws-0050",
      started: "2026-10-22T18:00:00+00:00",
      last: "2026-10-22T18:04:00+00:00",
      prompts: 1,
      tool_calls: 1,
      tools: ["Bash"],
      hosts: [],
      stopped: true,
      // The list says itself it was cut: 300 in the window, the newest 100 sent.
      total: 300,
      with_steps: 300,
    });
    spy.mockImplementation(async (input, init) => {
      const url = String(input);
      const res = await base(input, init);
      if (url.includes("/api/ai/sessions?"))
        return new Response(JSON.stringify(Array.from({ length: 100 }, (_, i) => one(i))));
      if (url.includes("/api/agents/overview")) {
        const body = await res.json();
        body.sessions.value = 310;
        body.session_parts = { listed: 300, empty: 0, telemetry_only: 10 };
        return new Response(JSON.stringify(body));
      }
      return res;
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
    const card = await screen.findByRole("region", { name: "Agent sessions" });
    const line = await within(card).findByText(/in the Sessions tile/);
    expect(line).toHaveTextContent(
      "310 sessions in the Sessions tile: 300 with step detail (newest 100 shown) · 10 seen only in Claude Code telemetry",
    );
    // The filter row agrees: 100 of the 300, never "100 sessions" as if that were all.
    expect(within(card).getByText("100 of 300 sessions")).toBeVisible();
  });

  it("reads accounts for the page's time", async () => {
    window.history.replaceState(null, "", "/agents/accounts#time=30d");
    const spy = await openAiAt();
    await screen.findByRole("region", { name: "Claude accounts" });
    expect(screen.getByText(/^Last 30 days, reported by the hooks plugin/)).toBeVisible();
    const asked = spy.mock.calls
      .map(([u]) => String(u))
      .find((u) => u.includes("/api/agents/accounts?"));
    const start = new URL(asked!, "http://x").searchParams.get("start");
    expect(Math.round((Date.now() - Date.parse(start!)) / 86_400_000)).toBe(30);
  });

  it("reads one window everywhere: an hour, exactly", async () => {
    window.history.replaceState(null, "", "/agents/mcp#time=1h");
    const spy = await openAiAt();
    await screen.findByRole("region", { name: "MCP servers" });
    const starts = (path: string) =>
      spy.mock.calls
        .map(([u]) => String(u))
        .filter((u) => u.includes(path))
        .map((u) => Date.parse(new URL(u, "http://x").searchParams.get("start") ?? ""));
    const [overview] = starts("/api/agents/overview?");
    expect(Math.round((Date.now() - overview!) / 60_000)).toBe(60);
    // A preset is never clamped: the MCP servers table reads the same hour, at once.
    const [usage] = starts("/api/ai/usage");
    expect(Math.abs(overview! - usage!)).toBeLessThan(60_000);
  });

  it("reads one window everywhere: a custom range in the past", async () => {
    const from = "2026-10-20T09:00:00.000Z";
    const to = "2026-10-21T09:00:00.000Z";
    window.history.replaceState(
      null,
      "",
      `/agents/sessions#time=custom&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`,
    );
    const spy = await openAiAt();
    await screen.findByRole("region", { name: "Agent sessions" });
    for (const path of ["/api/agents/overview?", "/api/ai/sessions?"]) {
      const u = new URL(
        spy.mock.calls.map(([x]) => String(x)).find((x) => x.includes(path))!,
        "http://x",
      );
      expect(u.searchParams.get("start")).toBe(from);
      // The end includes the minute it names.
      expect(Date.parse(u.searchParams.get("end")!) - Date.parse(to)).toBeLessThan(60_000);
    }
    // The strip names the range, not a number of days back from now.
    expect(
      await screen.findByText(/ to .*\. (Changes against|Comparisons start|No comparison)/),
    ).toBeVisible();
  });

  it("sends what was chosen: an open end stays open, a missing start stays missing", async () => {
    const from = "2026-10-20T09:00:00.000Z";
    const to = "2026-10-21T09:00:00.000Z";
    const reads = async (hash: string) => {
      vi.restoreAllMocks(); // a fresh spy: only this page's reads
      window.history.replaceState(null, "", `/agents/sessions#${hash}`);
      const spy = await openAiAt();
      await screen.findByRole("region", { name: "Agent sessions" });
      return spy.mock.calls
        .map(([u]) => String(u))
        .filter((u) => /\/api\/(agents\/overview|ai\/sessions|agents\/accounts)\?/.test(u))
        .map((u) => new URL(u, "http://x").searchParams);
    };
    // Custom from a start with an open end: the start as chosen, and no end.
    for (const q of await reads(`time=custom&from=${encodeURIComponent(from)}`)) {
      expect(q.get("start")).toBe(from);
      expect(q.get("end")).toBeNull();
    }
    // Custom with an end and no start: no start computed here; the server takes 90 days.
    for (const q of await reads(`time=custom&to=${encodeURIComponent(to)}`)) {
      expect(q.get("start")).toBeNull();
      expect(q.get("days")).toBe("90");
    }
  });

  it("says once when Agents reads less than the range chosen (the last 90 days of it)", async () => {
    const from = "2026-06-01T00:00:00.000Z";
    const to = "2026-10-20T00:00:00.000Z";
    vi.restoreAllMocks();
    window.history.replaceState(
      null,
      "",
      `/agents/sessions#time=custom&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`,
    );
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) => {
      const res = await base(input, init);
      if (!String(input).includes("/api/agents/overview")) return res;
      const body = await res.json();
      // What the server read: the 90 days to the chosen end.
      body.read_start = "2026-07-22T00:00:00+00:00";
      body.read_end = to;
      return new Response(JSON.stringify(body));
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
    const line = await screen.findByText(/^Agents shows at most 90 days: /);
    // The strip's words match what was read: the 90 days to the chosen end.
    expect((await screen.findAllByText(/^The 90 days to Oct 20/)).length).toBeGreaterThan(0);
    // Clamped: the MCP servers table reads from the start the overview read.
    // The page's own tab bar (the rail may list the same tabs, D268).
    const tabs = screen.getByRole("navigation", { name: "Agents tabs" });
    await userEvent.click(within(tabs).getByRole("link", { name: "MCP servers" }));
    await waitFor(() =>
      expect(
        spy.mock.calls
          .map(([x]) => String(x))
          .filter((x) => x.includes("/api/ai/usage"))
          .map((x) => new URL(x, "http://x").searchParams.get("start")),
      ).toContain("2026-07-22T00:00:00+00:00"),
    );
    expect(document.querySelectorAll("[data-agents-window]")).toHaveLength(1);
    expect(line.textContent).toMatch(/ to /);
  });

  it("updates the strip and Needs attention when an MCP server is reviewed", async () => {
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/agents/mcp");
    const spy = await openAiAt();
    const card = await screen.findByRole("region", { name: "MCP servers" });
    const overviews = () =>
      spy.mock.calls.filter(([u]) => String(u).includes("/api/agents/overview")).length;
    await waitFor(() => expect(overviews()).toBeGreaterThan(0));
    const before = overviews();
    const usages = spy.mock.calls.filter(([u]) => String(u).includes("/api/ai/usage")).length;
    await choose(within(card).getByLabelText("Review status of paste-share"), "approved");
    // The table, and the overview behind the tile and Needs attention, are read again.
    await waitFor(() => expect(overviews()).toBeGreaterThan(before));
    expect(
      spy.mock.calls.filter(([u]) => String(u).includes("/api/ai/usage")).length,
    ).toBeGreaterThan(usages);
  });

  describe("the MCP servers table follows the overview's counts (PR 639 final review)", () => {
    // The overview counts the table's rows by review state; `extra` adds one new server.
    const setup = async (hash: string) => {
      vi.restoreAllMocks();
      window.history.replaceState(null, "", `/agents/mcp#${hash}`);
      const spy = mockApi("Codename", { mode: "open" });
      const base = spy.getMockImplementation()!;
      const state = { extra: false };
      const fresh = {
        name: "new-mcp",
        status: "unreviewed",
        calls: 1,
        people: 1,
        machines: 1,
        installs: 0,
        clients: [],
        first_seen: "2026-10-30T11:59:00+00:00",
        last_seen: "2026-10-30T11:59:00+00:00",
        sources: ["hooks"],
      };
      const table = async (init?: RequestInit) => {
        const body = await (await base("/api/ai/usage", init)).json();
        if (state.extra) body.mcp = [...body.mcp, fresh];
        return body;
      };
      spy.mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.includes("/api/ai/usage")) return new Response(JSON.stringify(await table(init)));
        const res = await base(input, init);
        if (!url.includes("/api/agents/overview")) return res;
        const body = await res.json();
        const rows = (await table(init)).mcp as { status: string }[];
        body.mcp_not_approved.value = rows.filter((m) => m.status === "not_approved").length;
        body.mcp_unreviewed = rows.filter((m) => m.status === "unreviewed").length;
        return new Response(JSON.stringify(body));
      });
      vi.resetModules();
      const { loadBranding } = await import("@/lib/branding");
      await loadBranding();
      const { App } = await import("@/app/App");
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      render(<App initialTheme="dark" queryClient={client} />);
      await screen.findByRole("region", { name: "MCP servers" });
      const usage = () =>
        spy.mock.calls.filter(([u]) => String(u).includes("/api/ai/usage")).length;
      await waitFor(() => expect(usage()).toBeGreaterThan(0));
      return { spy, state, client, usage };
    };

    it("lists a new server within one overview read (a preset)", async () => {
      const { state, client, usage } = await setup("time=1h");
      const before = usage();
      state.extra = true;
      await client.refetchQueries({ queryKey: ["agents-overview"] });
      await waitFor(() => expect(usage()).toBe(before + 1));
      const card = await screen.findByRole("region", { name: "MCP servers" });
      expect(await within(card).findByText("new-mcp")).toBeVisible();
    });

    it("never re-reads the table while the counts agree (a clamped window)", async () => {
      const { client, usage } = await setup(
        `time=custom&from=${encodeURIComponent("2026-06-01T00:00:00.000Z")}`,
      );
      await waitFor(() => expect(usage()).toBe(1));
      await client.refetchQueries({ queryKey: ["agents-overview"] });
      await client.refetchQueries({ queryKey: ["agents-overview"] });
      await new Promise((r) => setTimeout(r, 50));
      expect(usage()).toBe(1);
    });
  });
});
