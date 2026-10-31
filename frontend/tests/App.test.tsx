import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";
import { setSql } from "./sqlEditor";

async function renderApp() {
  window.history.replaceState(null, "", "/search");
  window.localStorage.setItem("search-tab", "sql"); // these tests drive the SQL editor
  const fetchSpy = mockApi("Codename");
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
  await screen.findByRole("heading", { level: 1, name: "Investigate" });
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
  it("shows the product name from the API and the page hierarchy", async () => {
    await renderApp();
    expect(screen.getByText("Codename")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Investigate" })).toBeInTheDocument();
    // The area's tabs say where you are (ADR-0038); no breadcrumb.
    const tabs = screen.getByRole("navigation", { name: "Investigate tabs" });
    expect(within(tabs).getByRole("link", { name: "Search" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(tabs).getByRole("link", { name: "People & devices" })).toHaveAttribute(
      "href",
      "/investigate/people",
    );
    expect(window.location.pathname).toBe("/investigate/search");
  });

  it("uses plain, grouped navigation labels", async () => {
    await renderApp();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    // Four groups (ADR-0038 edit 10); Investigate lists its pages as rows.
    const groups = within(nav)
      .getAllByRole("region")
      .map((g) => g.getAttribute("aria-label"));
    expect(groups).toEqual(["Monitor", "Investigate", "AI", "System"]);
    const rows = (name: string) =>
      Array.from(within(within(nav).getByRole("region", { name })).getAllByRole("listitem"))
        .filter((li) => li.parentElement?.id === `rail-${name.toLowerCase()}`)
        .map((li) => li.querySelector("a")?.textContent);
    expect(rows("Monitor")).toEqual(["Dashboard", "Alerts", "Microsoft 365"]);
    expect(rows("Investigate")).toEqual(["Search", "People & devices", "Saved searches"]);
    expect(rows("AI")).toEqual(["AI usage", "Agents"]);
    expect(rows("System")).toEqual(["Health", "Settings"]);
    expect(within(nav).getByRole("link", { name: "Search" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).queryByText("Ask")).not.toBeInTheDocument(); // a tab of Search now
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

  it("lists every page's sub-pages and folds groups, remembered (ADR-0038 edit 10)", async () => {
    window.localStorage.removeItem("app.rail.collapsed");
    await renderApp();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    // Every page with sub-pages lists them, not only the open one.
    const health = within(nav).getByRole("list", { name: "Health pages" });
    expect(within(health).getByRole("link", { name: "Endpoint agents" })).toBeInTheDocument();
    const alerts = within(nav).getByRole("list", { name: "Alerts pages" });
    expect(within(alerts).getByRole("link", { name: "Rules" })).toHaveAttribute(
      "href",
      "/alerts/rules",
    );
    const fold = within(nav).getByRole("button", { name: "System group" });
    expect(fold).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(fold);
    expect(fold).toHaveAttribute("aria-expanded", "false");
    expect(window.localStorage.getItem("app.rail.collapsed")).toBe('["system"]');
    window.localStorage.removeItem("app.rail.collapsed");
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
    expect(nav).toHaveClass("hidden", "md:block");
    await userEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(nav).not.toHaveClass("hidden");
    expect(screen.getByRole("button", { name: "Close menu" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    await userEvent.click(within(nav).getByRole("link", { name: "Health" }));
    await screen.findByRole("heading", { level: 1, name: "Health" });
    expect(nav).toHaveClass("hidden");
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
    await waitFor(() =>
      expect(within(picker).getByRole("option", { name: "paloalto_traffic" })).toBeInTheDocument(),
    );
    await userEvent.selectOptions(picker, "paloalto_traffic");
    expect(screen.getByText("Source: paloalto_traffic")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run query" }));
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
    await userEvent.click(screen.getByRole("button", { name: "Run query" }));
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
    expect(firstRow()).toHaveTextContent("22:54:36"); // the earlier event first
    await userEvent.click(within(timeHeader).getByRole("button"));
    expect(timeHeader).toHaveAttribute("aria-sort", "descending");
    expect(firstRow()).toHaveTextContent("23:04:36");

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
