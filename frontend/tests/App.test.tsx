import { fromMore } from "./headerMenu";
import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";
import { setSql } from "./sqlEditor";
import { choose, optionLabels } from "./choose";

async function renderApp() {
  window.history.replaceState(null, "", "/search");
  window.localStorage.setItem("logs-tab", "sql"); // these tests drive the SQL editor
  const fetchSpy = mockApi("Codename");
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
  await screen.findByRole("heading", { level: 1, name: "Logs" });
  return fetchSpy;
}

function queryBodies(
  spy: ReturnType<typeof mockApi>,
): { sql: string; start?: string; sources?: string[] }[] {
  return spy.mock.calls
    .filter(([input]) => String(input).endsWith("/api/query"))
    .map(([, init]) => JSON.parse(String(init?.body)) as { sql: string });
}

describe("App shell", () => {
  it("shows the product name from the API and titles the page by its own name", async () => {
    await renderApp();
    expect(screen.getByText("Codename")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Logs" })).toBeInTheDocument();
    // The page's own tabs, which never repeat the rail (ADR-0052 3.2); no breadcrumb.
    const tabs = screen.getByRole("navigation", { name: "Logs tabs" });
    expect(within(tabs).getByRole("link", { name: "Search" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(tabs).getByRole("link", { name: "Saved searches" })).toHaveAttribute(
      "href",
      "/investigate/saved",
    );
    expect(within(tabs).getByRole("link", { name: "Library" })).toHaveAttribute(
      "href",
      "/investigate/library",
    );
    expect(within(tabs).queryByRole("link", { name: "Ask AI" })).toBeNull();
    expect(window.location.pathname).toBe("/investigate/logs");
  });

  it("lists pages in three labeled groups and a pinned cluster (ADR-0052 3.2, D268)", async () => {
    await renderApp();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const groups = within(nav)
      .getAllByRole("region")
      .map((g) => g.getAttribute("aria-label"));
    expect(groups).toEqual(["Monitor", "Investigate", "AI"]);
    const entries = (el: HTMLElement) =>
      [...el.querySelectorAll<HTMLElement>("[data-rail-entry]")].map(
        (a) => a.querySelector("span")?.textContent,
      );
    const rows = (name: string) => entries(within(nav).getByRole("region", { name }));
    expect(rows("Monitor")).toEqual(["Dashboard", "Alerts"]);
    expect(rows("Investigate")).toEqual(["Logs", "Ask AI", "People & devices"]);
    expect(rows("AI")).toEqual(["AI usage", "Agents"]);
    const pinned = within(nav).getByRole("list", { name: "Health and settings" });
    expect(entries(pinned)).toEqual(["Health", "Settings"]);
    // At most 10 entries for an administrator; only the current page (Logs) lists its tabs.
    expect(nav.querySelectorAll("[data-rail-entry]").length).toBeLessThanOrEqual(10);
    expect(nav.querySelectorAll("ul ul")).toHaveLength(1);
    expect(within(nav).queryAllByRole("button")).toEqual([]);
    expect(
      within(within(nav).getByRole("list", { name: "Logs tabs" }))
        .getAllByRole("link")
        .map((a) => a.textContent),
    ).toEqual(["Search", "Saved searches", "Library"]);
    expect(within(nav).queryByText("Microsoft 365")).toBeNull();
    expect(within(nav).getByRole("link", { name: "Logs" })).toHaveAttribute(
      "href",
      "/investigate/logs",
    );
    expect(within(nav).getByRole("link", { name: "Ask AI" })).toHaveAttribute("href", "/ask-ai");
    // Admin pages live in the Settings area, not on the main rail.
    expect(within(nav).queryByText("Users and access")).not.toBeInTheDocument();
    await userEvent.click(within(nav).getByRole("link", { name: "Settings" }));
    const sub = screen.getByRole("navigation", { name: "Settings" });
    // Ordered as an install is set up: start, data, access, AI, alerts, records.
    const text = sub.textContent ?? "";
    const order = ["Start here", "Data", "Access", "AI providers", "Alerts", "Records"].map((l) =>
      text.indexOf(l),
    );
    expect(order.every((at, i) => at >= 0 && (i === 0 || at > (order[i - 1] ?? -1)))).toBe(true);
    expect(within(sub).getByText("Users and access")).toBeInTheDocument();
    expect(within(sub).getByText("Audit log")).toBeInTheDocument();
    expect(screen.queryByText(/grimoire|seance|séance|ossuary/i)).not.toBeInTheDocument();
  });

  it("marks where you are with a bar and weight on exactly one entry, not a fill", async () => {
    await renderApp();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const here = [...nav.querySelectorAll<HTMLElement>("[data-rail-entry]")].filter((a) =>
      a.hasAttribute("aria-current"),
    );
    expect(here.map((a) => a.dataset.railEntry)).toEqual(["logs"]);
    // Logs has tabs, so its entry is the current section and its open tab the page (D268).
    expect(here[0]).toHaveAttribute("aria-current", "true");
    expect(
      within(nav)
        .getAllByRole("link")
        .filter((a) => a.getAttribute("aria-current") === "page")
        .map((a) => a.textContent),
    ).toEqual(["Search"]);
    expect(here[0]).toHaveClass(
      "before:w-0.5",
      "before:bg-accent-text",
      "font-semibold",
      "text-accent-text",
    );
    expect(here[0]).not.toHaveClass("bg-accent-subtle");
    // Pinned entries are a lower weight; the others are medium.
    expect(within(nav).getByRole("link", { name: /^Health/ })).toHaveClass("font-normal");
    expect(within(nav).getByRole("link", { name: /^Alerts/ })).toHaveClass("font-medium");
  });

  it("marks the page as the current section and its open tab, when a tab is open", async () => {
    window.history.replaceState(null, "", "/agents/sessions");
    mockApi("Codename");
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
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: "Agents" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(within(nav).getByRole("link", { name: "Sessions" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    const tabs = await screen.findByRole("navigation", { name: "Agents tabs" });
    expect(within(tabs).getByRole("link", { name: /^Sessions/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("shows the install name only when an admin set one", async () => {
    await renderApp();
    const top = screen.getByRole("banner");
    expect(within(top).queryByText("Security workspace")).toBeNull();
    await userEvent.click(
      within(screen.getByRole("navigation", { name: "Primary" })).getByRole("link", {
        name: "Settings",
      }),
    );
    await userEvent.click(screen.getByRole("link", { name: "About and licenses" }));
    const box = await screen.findByRole("region", { name: "Install name" });
    await userEvent.type(within(box).getByLabelText("Install name"), "Example SOC");
    await userEvent.click(within(box).getByRole("button", { name: "Save" }));
    expect(await within(top).findByText("Example SOC")).toBeInTheDocument();
  });

  it("toggles the theme on the root element", async () => {
    await renderApp();
    await userEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("on narrow screens, the Menu button shows the nav and navigating hides it again", async () => {
    await renderApp();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    // The rail holds the Primary nav and the Recent region (D258); the Menu button shows it.
    const rail = nav.closest("#primary-nav");
    expect(rail).toHaveClass("hidden", "md:grid");
    await userEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(rail).not.toHaveClass("hidden");
    expect(screen.getByRole("button", { name: "Close menu" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await userEvent.click(within(nav).getByRole("link", { name: "Health" }));
    await screen.findByRole("heading", { level: 1, name: "Health" });
    expect(rail).toHaveClass("hidden");
  });
});

describe("Search page", () => {
  it("runs on open with the selected time range and renders rows with severity and NULL glyph", async () => {
    const spy = await renderApp();
    expect(await screen.findByText("Failed password for invalid user oracle")).toBeInTheDocument();
    expect(screen.getByText("Medium")).toBeInTheDocument();
    expect(screen.getAllByText("·").length).toBeGreaterThan(0);
    const first = queryBodies(spy).find((b) => b.sql.includes("coalesce(time"));
    expect(first?.start).toBeTruthy();
  });

  it("expands a row inline and loads the full event with its raw line", async () => {
    await renderApp();
    const row = (await screen.findByText("Failed password for invalid user oracle")).closest(
      '[role="row"]',
    ) as HTMLElement | null;
    expect(row).not.toBeNull();
    await userEvent.click(row!);
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("Raw event")).toBeInTheDocument();
    expect(screen.getByText(/<38>Oct\s+9 23:04:36 bastion sshd\[4032\]/)).toBeInTheDocument();
    expect(screen.getByText("Local only")).toBeInTheDocument();
  });

  it("shows the rows around an event with the likely cause marked (ADR-0038 row 23)", async () => {
    await renderApp();
    const row = (await screen.findByText("Failed password for invalid user oracle")).closest(
      '[role="row"]',
    ) as HTMLElement;
    await userEvent.click(row);
    await userEvent.click(await screen.findByRole("button", { name: "Around this event" }));
    const box = await screen.findByRole("region", { name: "Around this event" });
    const cause = (await within(box).findByText("Likely cause")).closest("tr") as HTMLElement;
    expect(cause).toHaveTextContent("deny tcp 22");
    expect(within(cause).getByText("Likely cause")).toHaveAttribute(
      "title",
      expect.stringMatching(/^Likely cause: The nearest earlier row/),
    );
    expect(within(box).getByText("This event")).toBeVisible();
    await userEvent.click(within(box).getByRole("button", { name: "Open in Logs" }));
    expect(await screen.findByText(/From Around this event/)).toBeVisible();
  });

  it("shows guard rejections inline and runs on Ctrl+Enter", async () => {
    const spy = await renderApp();
    await screen.findByText("Failed password for invalid user oracle");
    const editor = await setSql("DROP TABLE events");
    fireEvent.keyDown(editor, { key: "Enter", ctrlKey: true });
    expect(await screen.findByRole("alert")).toHaveTextContent("Statement not allowed");
    expect(queryBodies(spy).some((b) => b.sql === "DROP TABLE events")).toBe(true);
  });

  it("runs the current SQL from the Run button beside the editor", async () => {
    const spy = await renderApp();
    await screen.findByText("Failed password for invalid user oracle");
    await setSql("SELECT source_id FROM events");
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() =>
      expect(queryBodies(spy).some((b) => b.sql === "SELECT source_id FROM events")).toBe(true),
    );
  });

  it("adds a source filter and sends it with the query", async () => {
    const spy = await renderApp();
    await screen.findByText("Failed password for invalid user oracle");
    const picker = await screen.findByLabelText("Add source filter");
    await waitFor(() => expect(optionLabels(picker)).toContain("paloalto_traffic"));
    await choose(picker, "paloalto_traffic");
    expect(screen.getByText("Source: paloalto_traffic")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() =>
      expect(queryBodies(spy).some((b) => b.sources?.includes("paloalto_traffic"))).toBe(true),
    );
  });
});

describe("SQL editor and raw view", () => {
  it("uses a code editor labelled for screen readers", async () => {
    await renderApp();
    const editor = await screen.findByLabelText("SQL query");
    expect(editor).toHaveClass("cm-content");
    expect(editor.textContent).toContain("FROM events");
  });

  it("shows raw lines for the page, looked up by event id, as text", async () => {
    const spy = await renderApp();
    await screen.findByText("Failed password for invalid user oracle");
    await userEvent.click(screen.getByRole("button", { name: "Raw" }));
    const list = await screen.findByRole("list", { name: "Raw events" });
    expect(
      await within(list).findByText(/<38>Oct\s+9 23:04:36 bastion sshd\[4032\]/),
    ).toBeInTheDocument();
    expect(queryBodies(spy).some((b) => b.sql.startsWith("SELECT event_id, raw FROM events"))).toBe(
      true,
    );
    await userEvent.click(screen.getByRole("button", { name: "Parsed" }));
    expect(screen.getByRole("treegrid", { name: "Search results" })).toBeVisible();
  });

  it("explains when a query has no raw lines", async () => {
    await renderApp();
    await screen.findByText("Failed password for invalid user oracle");
    await setSql("SELECT source_id, count(*) AS events FROM events GROUP BY source_id");
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    await screen.findByText("69");
    await userEvent.click(screen.getByRole("button", { name: "Raw" }));
    expect(screen.getByText(/Aggregates have no raw lines/)).toBeInTheDocument();
  });
});

describe("Empty results", () => {
  const base = {
    columns: ["time"],
    rows: [],
    row_count: 0,
    truncated: false,
    elapsed_ms: 1,
    executed_sql: "SELECT time FROM events",
  };

  it("says why when nothing is in scope, not just that nothing matched", async () => {
    const { ResultsTable } = await import("@/features/search/ResultsTable");
    const { rerender } = render(<ResultsTable result={{ ...base, sources: [] }} view="parsed" />);
    expect(screen.getByText("No sources to search")).toBeInTheDocument();
    expect(screen.getByText(/shares them through source groups/)).toBeInTheDocument();
    rerender(<ResultsTable result={{ ...base, sources: ["demo_vpn"] }} view="parsed" />);
    expect(screen.getByText("No events match")).toBeInTheDocument();
  });
});

describe("Results table controls", () => {
  it("sorts the shown rows by a header, then hides a column, then goes compact", async () => {
    await renderApp();
    const table = await screen.findByRole("treegrid", { name: "Search results" });
    await screen.findByText("Failed password for invalid user oracle");
    const timeHeader = within(table).getByRole("columnheader", { name: "Time" });
    expect(timeHeader).toHaveAttribute("aria-sort", "none");
    await userEvent.click(within(timeHeader).getByRole("button"));
    expect(timeHeader).toHaveAttribute("aria-sort", "ascending");
    const firstRow = () => within(table).getAllByRole("row")[1] as HTMLElement;
    expect(firstRow()).toHaveTextContent("10:54:36 PM"); // the earlier event first, local time
    await userEvent.click(within(timeHeader).getByRole("button"));
    expect(timeHeader).toHaveAttribute("aria-sort", "descending");
    expect(firstRow()).toHaveTextContent("11:04:36 PM");

    await userEvent.click(screen.getByRole("button", { name: "Columns" }));
    const chooser = screen.getByRole("group", { name: "Columns" });
    await userEvent.click(within(chooser).getByRole("checkbox", { name: "Host" }));
    expect(within(table).queryByRole("columnheader", { name: "Host" })).toBeNull();
    expect(screen.getByRole("button", { name: "Columns (some hidden)" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Compact" }));
    expect(screen.getByRole("button", { name: "Compact" })).toHaveAttribute("aria-pressed", "true");
    expect(table.parentElement?.style.getPropertyValue("--row-h")).toBe("30px");
  });
});

describe("Logs > Library (ADR-0033, owner 2026-11-17)", () => {
  const openLibrary = async () => {
    await userEvent.click(
      within(screen.getByRole("navigation", { name: "Logs tabs" })).getByRole("link", {
        name: "Library",
      }),
    );
    await screen.findByRole("region", { name: "Linux sign-ins and privilege" });
  };

  it("lists the packs with each query's description, Normal line, and sources", async () => {
    await renderApp();
    await openLibrary();
    expect(window.location.pathname).toBe("/investigate/library");
    expect(screen.getByRole("heading", { level: 1, name: "Logs" })).toBeInTheDocument();
    expect(
      within(screen.getByRole("navigation", { name: "Logs tabs" })).getByRole("link", {
        name: "Library",
      }),
    ).toHaveAttribute("aria-current", "page");
    const linux = screen.getByRole("region", { name: "Linux sign-ins and privilege" });
    expect(within(linux).getByText("SSH logins by user and source")).toBeVisible();
    // The short plain line Logs shows above the editor; the long text behind Details.
    expect(within(linux).getByText("Why SSH logins by user and source")).toBeVisible();
    expect(within(linux).queryByText("What SSH logins by user and source lists")).toBeNull();
    const details = within(linux).getByRole("button", {
      name: "Details of SSH logins by user and source",
    });
    expect(details).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(details);
    expect(details).toHaveAttribute("aria-expanded", "true");
    expect(within(linux).getByText("What SSH logins by user and source lists")).toBeVisible();
    expect(
      within(linux).getByText("Normal: Normal for SSH logins by user and source"),
    ).toBeVisible();
    expect(within(linux).getAllByText("Sources: Linux sshd authentication")).toHaveLength(2);
    // One count for the whole library, the queries of both groups.
    expect(screen.getByText("4 queries", { selector: "[data-filter-count]" })).toBeVisible();
    expect(screen.queryByText(/hidden|more queries need/i)).toBeNull();
  });

  it("lists the queries whose sources you lack, with the source names and Open disabled", async () => {
    await renderApp();
    await openLibrary();
    const needs = screen.getByRole("region", { name: "Needs sources you don't have" });
    expect(within(needs).getByText("Firewall admin sign-ins")).toBeVisible();
    expect(
      within(needs).getByText(
        "Sources, any one of: Palo Alto Networks system, Palo Alto Networks GlobalProtect",
      ),
    ).toBeVisible();
    const open = within(needs).getByRole("button", {
      name: "Run Firewall admin sign-ins in Logs",
    });
    expect(open).toHaveAttribute("aria-disabled", "true");
    expect(open).toHaveAccessibleDescription(
      "Needs a Palo Alto Networks system or Palo Alto Networks GlobalProtect source",
    );
    expect(open).toHaveAttribute("title", expect.stringMatching(/^Needs a Palo Alto/));
    // Only the name and the Sources line; one next step for the whole card.
    expect(within(needs).queryByText(/^Normal:/)).toBeNull();
    expect(within(needs).queryByText("Why Firewall admin sign-ins")).toBeNull();
    expect(within(needs).getByRole("link", { name: "Add a source" })).toHaveAttribute(
      "href",
      "/sources",
    );
    await userEvent.click(open);
    expect(window.location.pathname).toBe("/investigate/library");
    expect(within(needs).queryByRole("button", { name: /as my own|to the dashboard/ })).toBeNull();
  });

  it("filters by text and pack in one row, kept in the address", async () => {
    await renderApp();
    await openLibrary();
    await userEvent.type(
      screen.getByRole("textbox", { name: "Filter by name or description" }),
      "sudo",
    );
    expect(screen.getByText("1 of 4 queries", { selector: "[data-filter-count]" })).toBeVisible();
    expect(screen.queryByText("SSH logins by user and source")).toBeNull();
    expect(window.location.hash).toBe("#q=sudo");
    await userEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(screen.getByText("4 queries", { selector: "[data-filter-count]" })).toBeVisible();
  });

  it("Run opens the query in the SQL editor, unsaved, and only Logs' Run runs it", async () => {
    const spy = await renderApp();
    await openLibrary();
    const before = queryBodies(spy).length;
    await userEvent.click(
      screen.getByRole("button", { name: "Run SSH logins by user and source in Logs" }),
    );
    const note = await screen.findByRole("note", { name: "From the query library" });
    expect(window.location.pathname).toBe("/investigate/logs");
    expect(note).toHaveTextContent("Why SSH logins by user and source");
    expect(note).toHaveTextContent("Normal: Normal for SSH logins by user and source");
    expect(screen.getByRole("tab", { name: "SQL" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(/come from the time range above/)).toBeVisible();
    expect(screen.getByRole("button", { name: "24 hours" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // Loading is not running (ADR-0033 row 4): nothing ran on arrival.
    expect(queryBodies(spy).length).toBe(before);
    expect(screen.getByText("Press Run to see the rows.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(queryBodies(spy).at(-1)?.sql).toContain("actor_user_name"));
  });

  it("says the query's own words for no rows until its SQL is edited (D274)", async () => {
    const spy = await renderApp();
    const words = "No DHCP lease for this address in the range. It may be a static address.";
    const packSql =
      "SELECT time FROM events WHERE message LIKE '%dhcp%' AND device_ip = {{ip}} AND time BETWEEN {{start}} AND {{end}}";
    const loaded = packSql.replace("{{ip}}", "'10.20.1.5'");
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) => {
      const res = await base(input, init);
      const url = String(input);
      if (url.endsWith("/api/library")) {
        const body = await res.json();
        body.packs[0].queries.push({
          ...body.packs[0].queries[0],
          id: "who_had_ip",
          name: "Who had this address",
          sql: loaded,
          pack_sql: packSql,
          empty: words,
        });
        return new Response(JSON.stringify(body), {
          headers: { "content-type": "application/json" },
        });
      }
      if (!url.endsWith("/api/query") || !String(init?.body).includes("dhcp")) return res;
      const body = await res.json();
      return new Response(JSON.stringify({ ...body, rows: [], row_count: 0 }), {
        headers: { "content-type": "application/json" },
      });
    });
    await openLibrary();
    await userEvent.click(screen.getByRole("button", { name: "Run Who had this address in Logs" }));
    await screen.findByRole("note", { name: "From the query library" });
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(await screen.findByText(words)).toBeVisible();
    expect(screen.queryByText(/Try a wider time range/)).toBeNull();
    // Another address is the same query: its words still hold.
    await setSql(loaded.replace("10.20.1.5", "10.20.9.9"));
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(queryBodies(spy).at(-1)?.sql).toContain("10.20.9.9"));
    expect(await screen.findByText(words)).toBeVisible();
    // Any other edit makes it another query: the generic advice.
    await setSql(`${loaded} AND message LIKE '%dhcp%'`);
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(await screen.findByText(/Try a wider time range/)).toBeVisible();
    expect(screen.queryByText(words)).toBeNull();
  });

  it("saves a copy, adds one to the dashboard, and replaces an updated copy", async () => {
    const spy = await renderApp();
    await openLibrary();
    await userEvent.click(
      screen.getByRole("button", { name: "Save SSH logins by user and source as my own" }),
    );
    expect(
      spy.mock.calls.some(
        ([u, i]) =>
          String(u).endsWith("/api/library/linux_auth/ssh_logins/copy") && i?.method === "POST",
      ),
    ).toBe(true);
    await userEvent.click(
      screen.getByRole("button", { name: "Add SSH logins by user and source to the dashboard" }),
    );
    const added = spy.mock.calls.find(([u]) =>
      String(u).endsWith("/api/library/linux_auth/dashboard"),
    );
    expect(JSON.parse(String(added?.[1]?.body))).toMatchObject({ query_ids: ["ssh_logins"] });
    expect(
      await screen.findByText(/Added SSH logins by user and source to your dashboard/),
    ).toBeVisible();
    // Once added, the row links to the dashboard instead of offering the button again.
    expect(
      screen.queryByRole("button", { name: "Add SSH logins by user and source to the dashboard" }),
    ).toBeNull();
    const linux = screen.getByRole("region", { name: "Linux sign-ins and privilege" });
    expect(within(linux).getByRole("link", { name: "On your dashboard" })).toHaveAttribute(
      "href",
      "/dashboard",
    );
    expect(
      within(linux).getByRole("button", { name: "Add sudo refused to the dashboard" }),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Updated in this version" }));
    expect(screen.getByLabelText("Changes to sudo refused")).toHaveTextContent("- SELECT 1");
    await userEvent.click(screen.getByRole("button", { name: "Replace my copy" }));
    expect(
      spy.mock.calls.some(([u]) =>
        String(u).endsWith("/api/library/linux_auth/sudo_denied/replace"),
      ),
    ).toBe(true);
  });

  it("shows a query too long for Logs disabled, with the reason and no Save", async () => {
    await renderApp();
    await openLibrary();
    const big = screen.getByRole("button", { name: "Run AI services in use in Logs" });
    expect(big).toHaveAttribute("aria-disabled", "true");
    expect(big).toHaveAccessibleDescription(/longer than the 20,000 characters Logs takes/);
    expect(screen.queryByRole("button", { name: "Save AI services in use as my own" })).toBeNull();
  });

  it("opens from the Logs menu and from Ctrl+K", async () => {
    await renderApp();
    await userEvent.click(await fromMore("Library"));
    expect(window.location.pathname).toBe("/investigate/library");
    await screen.findByRole("region", { name: "Linux sign-ins and privilege" });
    await userEvent.click(
      within(screen.getByRole("navigation", { name: "Logs tabs" })).getByRole("link", {
        name: "Search",
      }),
    );
    await userEvent.keyboard("{Control>}k{/Control}");
    const palette = await screen.findByRole("dialog", { name: "Command palette" });
    await userEvent.type(within(palette).getByRole("combobox"), "query library");
    await userEvent.click(await within(palette).findByRole("option", { name: /Logs › Library/ }));
    expect(window.location.pathname).toBe("/investigate/library");
  });
});

describe("Live search (ADR-0036)", () => {
  it("parses server-sent events and skips keep-alives", async () => {
    const { parseSse } = await import("@/lib/liveStream");
    const got = parseSse(
      'event: rows\ndata: {"a":1}\n\n: ping\n\nevent: end\ndata: {}\n\nevent: pa',
    );
    expect(got.events).toEqual([
      ["rows", '{"a":1}'],
      ["end", "{}"],
    ]);
    expect(got.rest).toBe("event: pa");
  });

  it("follows new rows newest first, says how fresh each source is, and offers Resume", async () => {
    await renderApp();
    await screen.findByText("Failed password for invalid user oracle");
    await setSql("SELECT time, source_id, message, event_id FROM events");
    await userEvent.click(screen.getByRole("switch", { name: "Live" }));
    const live = await screen.findByRole("region", { name: "Live results" });
    expect(await within(live).findByText("deny tcp 203.0.113.9:8443")).toBeVisible();
    const rows = within(live).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("8443"); // newest at the top
    const fresh = within(live).getByLabelText("Freshness by source");
    expect(fresh).toHaveTextContent(
      "fw-edge 3 s, m365 4 min (pulls every 5 min), linux-auth 67 min",
    );
    expect(within(fresh).getByText(/linux-auth/)).toHaveClass("text-warn");
    expect(within(fresh).getByText(/m365/)).not.toHaveClass("text-warn");
    expect(
      within(live).getByText("Live stopped after 30 minutes. Resume to keep following."),
    ).toBeVisible();
    expect(within(live).getByRole("button", { name: "Resume" })).toBeVisible();
    await userEvent.click(within(live).getByRole("button", { name: "Stop" }));
    expect(screen.queryByRole("region", { name: "Live results" })).toBeNull();
  });

  it("says how far behind sources are and how often batches come", async () => {
    const { cadenceLine } = await import("@/features/search/LivePanel");
    const lag = [
      { source: "loki", newest: null, age_s: 190, pull_every_s: null },
      { source: "fw", newest: null, age_s: 170, pull_every_s: null },
      { source: "old", newest: null, age_s: null, pull_every_s: null },
    ];
    expect(cadenceLine(lag, [0, 30_000, 61_000, 90_000])).toBe(
      "Sources are about 3 min behind; new events arrive about every 30 s.",
    );
    expect(cadenceLine(lag, [0])).toBe("Sources are about 3 min behind.");
    expect(
      cadenceLine([{ source: "fw", newest: null, age_s: 2, pull_every_s: null }], [0, 2000, 4000]),
    ).toBe(null);
  });

  it("keeps the open row open and in place when rows arrive above it", async () => {
    const { ResultsTable } = await import("@/features/search/ResultsTable");
    const base = {
      columns: ["message", "event_id"],
      row_count: 2,
      truncated: false,
      elapsed_ms: 0,
      executed_sql: "",
      sources: ["fw"],
    };
    const first = [
      ["older", "e1"],
      ["oldest", "e0"],
    ];
    const opened = vi.fn();
    const { QueryClientProvider } = await import("@tanstack/react-query");
    const client = new QueryClient();
    const { rerender } = render(
      <QueryClientProvider client={client}>
        <ResultsTable result={{ ...base, rows: first }} view="parsed" onOpenChange={opened} />
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByText("older"));
    expect(opened).toHaveBeenLastCalledWith(true);
    rerender(
      <QueryClientProvider client={client}>
        <ResultsTable
          result={{ ...base, rows: [["newest", "e2"], ...first] }}
          view="parsed"
          onOpenChange={opened}
        />
      </QueryClientProvider>,
    );
    const open = screen
      .getAllByRole("row")
      .filter((r) => r.getAttribute("aria-expanded") === "true");
    expect(open).toHaveLength(1);
    expect(open[0]).toHaveTextContent("older");
  });

  it("starts with the last 5 minutes when asked, and remembers the choice", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    await renderApp();
    await screen.findByText("Failed password for invalid user oracle");
    await setSql("SELECT time, source_id, message, event_id FROM events");
    await userEvent.click(screen.getByRole("checkbox", { name: "Start with the last 5 min" }));
    await userEvent.click(screen.getByRole("switch", { name: "Live" }));
    await screen.findByRole("region", { name: "Live results" });
    expect(
      spy.mock.calls.some(
        ([u]) => String(u).includes("/api/search/live?") && String(u).includes("fill_minutes=5"),
      ),
    ).toBe(true);
    expect(localStorage.getItem("app.live.fill")).toBe("1");
    localStorage.removeItem("app.live.fill");
  });

  it("says why a group query cannot go live, and lists open streams when refused", async () => {
    await renderApp();
    await screen.findByText("Failed password for invalid user oracle");
    await setSql("SELECT source_id, count(*) FROM events GROUP BY 1");
    await userEvent.click(screen.getByRole("switch", { name: "Live" }));
    const live = await screen.findByRole("region", { name: "Live results" });
    expect(await within(live).findByText(/Live works on event rows/)).toBeVisible();
    await userEvent.click(screen.getByRole("switch", { name: "Live" }));
    await setSql("SELECT message FROM events WHERE message = 'refuse'");
    await userEvent.click(screen.getByRole("switch", { name: "Live" }));
    const again = await screen.findByRole("region", { name: "Live results" });
    expect(await within(again).findByText(/2 live searches open/)).toBeVisible();
    expect(
      await within(again).findByRole("button", { name: "Stop tail -f since 13:40 UTC" }),
    ).toBeVisible();
  });
});
