import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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

describe("AI usage (ADR-0015)", () => {
  it("shows services with review status and lets an admin change it", async () => {
    const spy = await openAi();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: "AI usage" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(await screen.findByText("1 not approved in use")).toBeVisible();
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

  it("saves the AI watch", async () => {
    const spy = await openAi();
    await goTo("AI usage", "Review");
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
    const filters = within(card).getByRole("group", { name: "Filter sessions" });
    await userEvent.selectOptions(within(filters).getByRole("combobox", { name: "Tool" }), "Bash");
    expect(within(list).queryByText("dana@example.com")).toBeNull();
    expect(within(filters).getByText("1 of 2 shown")).toBeVisible();
    await userEvent.selectOptions(within(filters).getByRole("combobox", { name: "Tool" }), "");
    await userEvent.click(within(filters).getByRole("checkbox", { name: "Has flags" }));
    expect(within(list).queryByText("alice@example.com")).toBeNull();
    expect(within(list).getByText("dana@example.com")).toBeVisible();
    await userEvent.selectOptions(
      within(filters).getByRole("combobox", { name: "Machine" }),
      "ws-0311",
    );
    expect(within(card).getByText("No sessions match these filters.")).toBeVisible();
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
    const types = within(card).getByRole("group", { name: "Type" });
    expect(within(types).getByRole("button", { name: /^MCP servers 1/ })).toBeVisible();
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
    expect(window.location.pathname).toBe("/investigate/search");
  });

  it("lists tools with their type and status", async () => {
    await openAt("/agents/tools");
    const box = await screen.findByRole("region", { name: "Tools" });
    const row = (await within(box).findByText("paste-share")).closest("tr") as HTMLElement;
    expect(within(row).getByText("MCP server")).toBeVisible();
    expect(within(row).getByText("Not approved")).toBeVisible();
    const bash = within(box).getByText("Bash").closest("tr") as HTMLElement;
    expect(within(bash).getByText("Built in")).toBeVisible();
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
});
