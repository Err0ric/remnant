import { QueryClient } from "@tanstack/react-query";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";
import { choose, optionLabels } from "./choose";

/** A mix: an unreviewed service and MCP server, an approved and a not approved one, and an
 * unreviewed service someone excluded. Items outside the window and on sources the caller
 * cannot read never reach the page: the server leaves them out (test_ai_inventory.py). */
function mix() {
  const seen = {
    people: 1,
    devices: 1,
    first_seen: "2026-10-20T10:00:00+00:00",
    last_seen: "2026-10-30T10:00:00+00:00",
    where: ["Network and proxy logs"],
  };
  return [
    {
      ...seen,
      type: "service",
      key: "chatgpt",
      name: "ChatGPT",
      status: "unreviewed",
      excluded: null,
    },
    { ...seen, type: "mcp", key: "jira", name: "jira", status: "unreviewed", excluded: null },
    { ...seen, type: "service", key: "claude", name: "Claude", status: "approved", excluded: null },
    {
      ...seen,
      type: "mcp",
      key: "paste-share",
      name: "paste-share",
      status: "not_approved",
      excluded: null,
    },
    {
      ...seen,
      type: "service",
      key: "deepseek",
      name: "DeepSeek",
      status: "unreviewed",
      excluded: { reason: "Blocked at the proxy", by: "admin", at: "2026-10-29T10:00:00Z" },
    },
  ];
}

async function open(path: string, role: "admin" | "analyst", inventory = mix()) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role, inventory });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
  await screen.findByRole("heading", { level: 1 });
  return spy;
}

let client: QueryClient;

/** Every place that states the number: the header, the rail, Needs attention, and the
 * table with Status = Unreviewed (its rows and its count). */
async function expectEverywhere(n: number) {
  const header = () => document.querySelector("[data-header-count]");
  await vi.waitFor(() => expect(header()).toHaveTextContent(new RegExp(`^${n} to review$`)));
  const nav = screen.getByRole("navigation", { name: "Primary" });
  const ai = within(nav).getByRole("link", { name: /^AI usage/ });
  await vi.waitFor(() =>
    expect(ai.querySelector("[data-ai-count]")).toHaveAttribute("aria-label", `${n} to review`),
  );
  const attention = screen.getByRole("region", { name: "Needs attention" });
  expect(strip().slice(1, 3)).toEqual([
    `${n} ${n === 1 ? "item" : "items"} to review`,
    "1 item marked Not approved",
  ]);
  expect(attention).not.toHaveTextContent(/unreviewed AI service/);
  const card = screen.getByRole("region", { name: "AI inventory" });
  expect(within(card).getByRole("combobox", { name: "Status" })).toHaveValue("unreviewed");
  await vi.waitFor(() => expect(within(card).getAllByRole("row")).toHaveLength(n + 1));
  expect(card.querySelector("[data-filter-count]")).toHaveTextContent(`${n} of 4 items`);
}

/** The Needs attention line's entries, in order. */
function strip(): string[] {
  const attention = screen.getByRole("region", { name: "Needs attention" });
  return within(attention)
    .getAllByRole("button")
    .map((b) => b.textContent ?? "");
}

afterEach(() => vi.restoreAllMocks());

describe("One to-review number (owner, 2026-11-16)", () => {
  it.each(["admin", "analyst"] as const)(
    "the header, the rail, Needs attention, and the table agree for an %s",
    async (role) => {
      await open("/ai/inventory", role);
      await screen.findByRole("region", { name: "AI inventory" });
      await expectEverywhere(2);
    },
  );

  it("changes everywhere at once after a review", async () => {
    const spy = await open("/ai/inventory", "admin");
    const card = await screen.findByRole("region", { name: "AI inventory" });
    await expectEverywhere(2);
    await choose(
      within(card).getByRole("combobox", { name: "Review status of ChatGPT" }),
      "approved",
    );
    await expectEverywhere(1);
    expect(
      spy.mock.calls.some(
        ([u, init]) =>
          String(u).endsWith("/api/ai/services/chatgpt/status") && init?.method === "PUT",
      ),
    ).toBe(true);
  });

  it("draws the same Needs attention line on all three tabs, from the Inventory's numbers", async () => {
    const seen: string[][] = [];
    for (const path of ["/ai", "/ai/people", "/ai/inventory"]) {
      await open(path, "admin");
      await screen.findByRole("region", { name: "Needs attention" });
      await vi.waitFor(() => expect(strip()).toContain("2 items to review"));
      seen.push(strip());
      cleanup();
    }
    expect(seen[0]).toEqual([
      expect.stringMatching(/^\d+ open alerts?$/),
      "2 items to review",
      "1 item marked Not approved",
      "1 sensitive-data signal",
    ]);
    expect(seen[1]).toEqual(seen[0]);
    expect(seen[2]).toEqual(seen[0]);
    // Each opens the Inventory filtered to what it counts.
    await open("/ai/people", "admin");
    await screen.findByRole("region", { name: "Needs attention" });
    await vi.waitFor(() => expect(strip()).toContain("1 item marked Not approved"));
    await userEvent.click(screen.getByRole("button", { name: "1 item marked Not approved" }));
    expect(window.location.pathname + window.location.hash).toBe(
      "/ai/inventory#status=not_approved",
    );
    const card = await screen.findByRole("region", { name: "AI inventory" });
    await within(card).findByText("paste-share");
    expect(within(card).getAllByRole("row")).toHaveLength(2);
  });

  it("keeps the time chosen when a Needs attention link opens the Inventory", async () => {
    await open("/ai#time=30d", "admin");
    await screen.findByRole("region", { name: "Needs attention" });
    await vi.waitFor(() => expect(strip()).toContain("2 items to review"));
    await userEvent.click(screen.getByRole("button", { name: "2 items to review" }));
    expect(window.location.pathname).toBe("/ai/inventory");
    expect(new URLSearchParams(window.location.hash.slice(1)).get("time")).toBe("30d");
    await screen.findByRole("region", { name: "AI inventory" });
    const tabs = screen.getByRole("navigation", { name: "AI usage tabs" });
    await userEvent.click(within(tabs).getByRole("link", { name: "Services" }));
    const time = await screen.findByRole("group", { name: "Time" });
    expect(within(time).getByRole("button", { name: "30 days" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("keeps the Inventory's own answer while its tab is open, even when a newer count differs", async () => {
    await open("/ai/inventory", "admin");
    await screen.findByRole("region", { name: "AI inventory" });
    await expectEverywhere(2);
    // A count answer newer than the page's and different from it (as after minutes open).
    act(() =>
      client.setQueryData(["ai-usage", "inventory", "count"], { to_review: 7, not_approved: 5 }),
    );
    await new Promise((r) => setTimeout(r, 50));
    await expectEverywhere(2);
  });

  it("says the exports are waiting while the items load", async () => {
    window.history.replaceState(null, "", "/ai/inventory");
    const spy = mockApi("Codename", {
      mode: "login",
      signedIn: true,
      role: "admin",
      inventory: mix(),
    });
    const base = spy.getMockImplementation() as typeof fetch;
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    spy.mockImplementation(async (input, init) => {
      if (/\/api\/ai\/inventory\?/.test(String(input))) await held;
      return base(input, init);
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    render(<App initialTheme="dark" queryClient={new QueryClient()} />);
    const csv = await screen.findByRole("button", { name: "Export CSV of the items listed below" });
    expect(csv).toBeDisabled();
    expect(csv).toHaveAttribute("title", "Loading items");
    release();
    await vi.waitFor(() => expect(csv).toBeEnabled());
    expect(csv).toHaveAttribute("title", "Export the items listed below as CSV");
  });

  it("states the same number on the other tabs, which keep their time control", async () => {
    await open("/ai/services", "admin");
    const attention = await screen.findByRole("region", { name: "Needs attention" });
    await vi.waitFor(() => expect(attention).toHaveTextContent("2 items to review"));
    expect(attention).not.toHaveTextContent(/unreviewed AI service|in use/);
    expect(screen.getByRole("group", { name: "Time" })).toBeVisible();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const ai = within(nav).getByRole("link", { name: /^AI usage/ });
    await vi.waitFor(
      () =>
        expect(ai.querySelector("[data-ai-count]")).toHaveAttribute("aria-label", "2 to review"),
      { timeout: 5000 },
    );
  });
});

describe("The Inventory tab's controls (owner, 2026-11-16)", () => {
  it("has no time control and keeps the other tabs' time in the address", async () => {
    await open("/ai#time=30d", "admin");
    await screen.findByRole("group", { name: "Time" });
    const tabs = screen.getByRole("navigation", { name: "AI usage tabs" });
    await userEvent.click(within(tabs).getByRole("link", { name: "Inventory" }));
    await screen.findByRole("region", { name: "AI inventory" });
    expect(screen.queryByRole("group", { name: "Time" })).toBeNull();
    expect(screen.queryByText(/Against the previous/)).toBeNull();
    expect(within(tabs).getByRole("link", { name: "Services" })).toHaveAttribute(
      "href",
      "/ai#time=30d",
    );
  });

  it("has one filter row, a title that is not the tab's name, and no grouping that makes one group", async () => {
    await open("/ai/inventory", "admin");
    const card = await screen.findByRole("region", { name: "AI inventory" });
    expect(document.querySelectorAll("[data-filter-bar]")).toHaveLength(1);
    const head = card.querySelector<HTMLElement>("[data-card-header]")!;
    expect(head).not.toHaveTextContent(/^Inventory/);
    expect(head).toHaveTextContent("In the last 30 days, from the sources you can read.");
    // Status is Unreviewed: grouping by Status would make one group, so only Type is offered.
    const group = within(card).getByRole("combobox", { name: "Group by" });
    await userEvent.click(group);
    const list = await screen.findByRole("listbox");
    expect(
      within(list)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["None", "Type"]);
    await userEvent.keyboard("{Escape}");
    // One type and one status chosen: no grouping does anything, so Group by goes.
    await choose(within(card).getByRole("combobox", { name: "Type" }), "mcp");
    expect(within(card).queryByRole("combobox", { name: "Group by" })).toBeNull();
  });

  it("names the header's exports for what they export, and turns them off with nothing listed", async () => {
    await open("/ai/inventory", "admin");
    const card = await screen.findByRole("region", { name: "AI inventory" });
    await within(card).findByText("ChatGPT");
    const csv = screen.getByRole("button", { name: "Export CSV of the items listed below" });
    expect(csv).toHaveTextContent("Export CSV");
    expect(csv).toHaveAttribute("title", "Export the items listed below as CSV");
    expect(csv).toBeEnabled();
    // MCP servers marked Approved: none in this mix.
    await choose(within(card).getByRole("combobox", { name: "Type" }), "mcp");
    await choose(within(card).getByRole("combobox", { name: "Status" }), "approved");
    expect(within(card).getByText("Nothing matches these filters.")).toBeVisible();
    for (const f of ["CSV", "JSON"]) {
      const b = screen.getByRole("button", { name: `Export ${f} of the items listed below` });
      expect(b).toBeDisabled();
      expect(b).toHaveAttribute("title", "Nothing to export: no items are listed below");
    }
  });

  it("offers only types with items in the view, and falls back to All for an empty one", async () => {
    await open("/ai/inventory#type=m365_app", "admin");
    const card = await screen.findByRole("region", { name: "AI inventory" });
    await within(card).findByText("ChatGPT");
    const type = within(card).getByRole("combobox", { name: "Type" });
    expect(type).toHaveValue("");
    expect(optionLabels(type)).toEqual(["All (4)", "AI services (2)", "MCP servers (2)"]);
    // Excluded holds one service only: a Type list would list the same for every choice.
    await userEvent.click(within(card).getByRole("button", { name: /^Excluded/ }));
    await within(card).findByText("DeepSeek");
    expect(within(card).queryByRole("combobox", { name: "Type" })).toBeNull();
    expect(within(card).queryByRole("combobox", { name: "Group by" })).toBeNull();
  });

  it("says in a plain sentence that nothing is excluded", async () => {
    await open(
      "/ai/inventory",
      "admin",
      mix().filter((i) => i.excluded === null),
    );
    const card = await screen.findByRole("region", { name: "AI inventory" });
    await within(card).findByText("ChatGPT");
    await userEvent.click(within(card).getByRole("button", { name: /^Excluded/ }));
    expect(
      await within(card).findByText(
        "Nothing is excluded. Excluded items move here with who excluded them and why.",
      ),
    ).toBeVisible();
  });
});
