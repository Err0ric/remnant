import { QueryClient } from "@tanstack/react-query";
import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

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
    const row = within(people).getByText("alice@example.com").closest("tr") as HTMLElement;
    expect(within(row).getAllByText("No cost data")).toHaveLength(2);
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
    expect(
      within(people).getByText(
        "Names are hidden. An admin can turn on View people in AI usage for you.",
      ),
    ).toBeVisible();
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
    expect(within(nav).getByRole("link", { name: "AI usage" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(await screen.findByText("1 service not approved in use")).toBeVisible();
    const table = screen.getByRole("region", { name: "AI services seen in network logs" });
    const row = within(table).getByText("ChatGPT").closest("tr") as HTMLElement;
    expect(within(row).getByText("Not approved")).toBeVisible();
    // Review opens under the row (list-detail), not inline in the table.
    await userEvent.click(within(row).getByRole("button", { name: "Review ChatGPT" }));
    const picker = within(table).getByLabelText("Review status of ChatGPT");
    expect(picker).toHaveValue("not_approved");
    await userEvent.selectOptions(picker, "approved");
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

  it("shows vendor ad tags apart and never as a service in use", async () => {
    await openAi();
    const table = await screen.findByRole("region", { name: "AI services seen in network logs" });
    expect(within(table).queryByText("OpenAI ad and measurement tags")).toBeNull();
    const apart = screen.getByRole("group", { name: "Not counted as AI use" });
    expect(within(apart).getByText("1 host group, 900 events")).toBeInTheDocument();
    expect(within(apart).getByText("bzr.openai.com, bzrcdn.openai.com")).toBeInTheDocument();
  });

  it("lists agents with what changed and sets a service's allowed data", async () => {
    const spy = await openAi();
    const table = await screen.findByRole("region", { name: "AI services seen in network logs" });
    const row = within(table).getByText("ChatGPT").closest("tr") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Review ChatGPT" }));
    await userEvent.selectOptions(
      within(table).getByLabelText("Allowed data for ChatGPT"),
      "internal",
    );
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
    const row = within(people).getByText("alice@example.com").closest("tr") as HTMLElement;
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
      within(services).getByText(/Seen through: both 1, plugin only 1, network only 1/),
    ).toBeVisible();
    await goTo("AI usage", "People");
    const people = await screen.findByRole("region", { name: "Claude Code by person" });
    expect(within(people).getByText(/Seen on the network but no plugin: 1/)).toBeVisible();
    const erin = within(people).getByText("erin@example.com").closest("tr") as HTMLElement;
    expect(within(erin).getByText("Plugin")).toHaveAttribute(
      "title",
      "The hooks only: not seen on the network",
    );
    const dana = within(people).getByText("dana@example.com").closest("tr") as HTMLElement;
    expect(within(dana).getByText("Network")).toBeVisible();
    // D190: cost and tokens only from telemetry; network rows say what the network saw,
    // and a name that reads as a plugin person links to Identities, filled in.
    expect(within(erin).getAllByText("Not reported")).toHaveLength(2);
    expect(within(erin).queryByText("0.00")).toBeNull();
    expect(dana).toHaveTextContent(/Network only: Claude, 40 lookups, 2 devices, last seen /);
    expect(dana).toHaveTextContent("Unmatched: may be dana.lee@example.com.");
    const link = within(dana).getByRole("link", { name: "Link in Identities" });
    expect(link.getAttribute("href")).toMatch(/#alias=dlee&person=dana\.lee%40example\.com$/);
    const alice = within(people).getByText("alice@example.com").closest("tr") as HTMLElement;
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
    const detail = await within(card).findByRole("region", { name: "Session detail" });
    expect(within(detail).getByText("Claude account")).toBeVisible();
    const steps = await within(detail).findByRole("list", { name: "Session timeline" });
    // By turn (D187): the prompt, its tool calls each with its result, then the end.
    const turn = within(steps).getByRole("list", { name: "Turn 1" });
    const rows = within(turn).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent?.replace(/^\d{1,2}:\d{2}:\d{2}\s[AP]M/, ""))).toEqual([
      expect.stringMatching(/^Prompt42 chars/),
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
    expect(within(card).getByText("Pick a session.").closest("[data-empty]")).toHaveAttribute(
      "data-empty",
      "default-empty",
    );
    const filters = within(card).getByRole("group", { name: "Filter sessions" });
    await userEvent.selectOptions(within(filters).getByRole("combobox", { name: "Tool" }), "Bash");
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
    await userEvent.selectOptions(
      within(filters).getByRole("combobox", { name: "Flags" }),
      "flagged",
    );
    expect(within(list).queryByText("alice@example.com")).toBeNull();
    expect(within(list).getByText("dana@example.com")).toBeVisible();
    await userEvent.selectOptions(
      within(filters).getByRole("combobox", { name: "Machine" }),
      "ws-0311",
    );
    expect(within(card).getByText("No sessions match these filters.")).toBeVisible();
    // The open session is the one in the address: Back undoes the filter and closes it.
    await userEvent.click(within(filters).getByRole("button", { name: "Reset" }));
    window.history.replaceState(null, "", "/agents/sessions");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await userEvent.selectOptions(
      within(filters).getByRole("combobox", { name: "Tool" }),
      "github",
    );
    await userEvent.click(
      within(within(card).getByRole("list", { name: "Sessions" })).getByText("dana@example.com"),
    );
    expect(await within(card).findByRole("region", { name: "Session detail" })).toBeVisible();
    expect(window.location.hash).toBe("#tool=github&session=s-77");
    window.history.back();
    await waitFor(() => expect(window.location.hash).toBe(""));
    await waitFor(() =>
      expect(within(card).queryByRole("region", { name: "Session detail" })).toBeNull(),
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
    expect(within(card).getByText(/Names are hidden\. An admin can turn on/)).toBeVisible();
    // No person filter: it would list machines as people.
    const filters = within(card).getByRole("group", { name: "Filter sessions" });
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
    const detail = await within(card).findByRole("region", { name: "Session detail" });
    expect(within(detail).queryByRole("link", { name: /dana|Hidden/ })).toBeNull();
    // A machine is not looked up as an account: no other account's tier.
    expect(within(detail).getByText("Hidden")).toBeVisible();
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
    expect(within(type).getByRole("option", { name: "MCP servers (1)" })).toBeInTheDocument();
    expect(
      within(type).getByRole("option", { name: /^Microsoft 365 apps \(\d+\)$/ }),
    ).toBeInTheDocument();
    expect(within(card).getByRole("combobox", { name: "Status" })).toHaveValue("all");
    expect(document.querySelector("[data-header-count]")).toHaveTextContent(/^0 to review$/);
    expect(within(card).queryByRole("button", { name: "Reset" })).toBeNull();
    await userEvent.selectOptions(
      within(card).getByRole("combobox", { name: "Status" }),
      "approved",
    );
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
    expect(within(card).getByRole("button", { name: "Export CSV" })).toBeVisible();
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
    await userEvent.selectOptions(
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
    await userEvent.selectOptions(within(card).getByRole("combobox", { name: "Status" }), "all");
    await userEvent.selectOptions(
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
    await userEvent.click(within(card).getByRole("button", { name: "Export CSV" }));
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
    await userEvent.selectOptions(
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

  it("counts the strip in whole days and says so, whatever the page's time", async () => {
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
    const days = () =>
      spy.mock.calls
        .map(([u]) => String(u))
        .filter((u) => u.includes("/api/agents/overview"))
        .map((u) => new URL(u, "http://x").searchParams.get("days"));
    const strip = await screen.findByRole("region", { name: "Overview" });
    expect(days().at(-1)).toBe("7");
    // On the strip and on the sessions list under it.
    expect(screen.getAllByText(/^Last 7 days\./).length).toBeGreaterThanOrEqual(1);
    expect(
      await within(await screen.findByRole("region", { name: "Agent sessions" })).findByText(
        /^Last 7 days\. Claude Code and Cowork sessions/,
      ),
    ).toBeVisible();
    // The note about devices that sent nothing, and a number opening its rows in Logs.
    expect(within(strip).getByRole("note")).toHaveTextContent("ws-0420");
    const time = screen.getByRole("group", { name: "Time" });
    await userEvent.click(within(time).getByRole("button", { name: "30 days" }));
    await waitFor(() => expect(days().at(-1)).toBe("30"));
    expect((await screen.findAllByText(/^Last 30 days\./)).length).toBeGreaterThanOrEqual(1);
    // 1 hour is still a day of sessions, and the words say a day, not an hour.
    await userEvent.click(within(time).getByRole("button", { name: "1 hour" }));
    await waitFor(() => expect(days().at(-1)).toBe("1"));
    const caption = (await screen.findAllByText(/^Last 24 hours\./))[0] as HTMLElement;
    expect(caption).not.toHaveTextContent(/previous hour/);
    // The sessions list covers the same days as the strip above it.
    expect(
      spy.mock.calls
        .map(([u]) => String(u))
        .filter((u) => u.includes("/api/ai/sessions?"))
        .at(-1),
    ).toContain("days=1");
    // Custom counts whole days from its start to now, 30 at most.
    await userEvent.click(within(time).getByRole("button", { name: "Custom" }));
    const { fireEvent } = await import("@testing-library/react");
    const pad = (n: number) => String(n).padStart(2, "0");
    const back = (daysAgo: number) => {
      const d = new Date(Date.now() - daysAgo * 86_400_000 + 3_600_000);
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    };
    fireEvent.change(screen.getByLabelText("From"), { target: { value: back(3) } });
    await waitFor(() => expect(days().at(-1)).toBe("3"));
    expect((await screen.findAllByText(/^Last 3 days\./)).length).toBeGreaterThanOrEqual(1);
    fireEvent.change(screen.getByLabelText("From"), { target: { value: back(200) } });
    await waitFor(() => expect(days().at(-1)).toBe("30"));
    await userEvent.click(within(time).getByRole("button", { name: "1 hour" }));
    await waitFor(() => expect(days().at(-1)).toBe("1"));
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
    expect(await within(card).findByText(/Names are hidden\. An admin can turn on/)).toBeVisible();
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
    expect(within(card).getByText(/Names are hidden\. An admin can turn on/)).toBeVisible();
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
    expect(within(card).getByText(/Names are hidden\. An admin can turn on/)).toBeVisible();
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
