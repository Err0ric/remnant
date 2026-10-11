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
  await screen.findByRole("heading", { level: 1, name: "Search" });
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
    expect(screen.getByRole("heading", { level: 1, name: "Search" })).toBeInTheDocument();
    expect(screen.getByText(/Home\s+›\s+Investigate\s+›\s+Search/)).toBeInTheDocument();
  });

  it("uses plain, grouped navigation labels", async () => {
    await renderApp();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    for (const label of [
      "Investigate",
      "Search",
      "Saved searches",
      "Configuration",
      "Users and access",
      "Audit log",
    ]) {
      expect(within(nav).getByText(label)).toBeInTheDocument();
    }
    expect(within(nav).getByText("Search")).toHaveAttribute("aria-current", "page");
    expect(within(nav).queryByText("Ask")).not.toBeInTheDocument(); // a tab of Search now
    expect(screen.queryByText(/grimoire|seance|séance|ossuary/i)).not.toBeInTheDocument();
  });

  it("toggles the theme on the root element", async () => {
    await renderApp();
    await userEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement.dataset.theme).toBe("light");
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
      "button",
    );
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
    const editor = setSql("DROP TABLE events");
    fireEvent.keyDown(editor, { key: "Enter", ctrlKey: true });
    expect(await screen.findByRole("alert")).toHaveTextContent("Statement not allowed");
    expect(queryBodies(spy).some((b) => b.sql === "DROP TABLE events")).toBe(true);
  });

  it("runs the current SQL from the Run button beside the editor", async () => {
    const spy = await renderApp();
    await screen.findByText("Failed password for invalid user oracle");
    setSql("SELECT source_id FROM events");
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
    const editor = screen.getByLabelText("SQL query");
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
    expect(screen.getByRole("table", { name: "Search results" })).toBeVisible();
  });

  it("explains when a query has no raw lines", async () => {
    await renderApp();
    await screen.findByText("Failed password for invalid user oracle");
    setSql("SELECT source_id, count(*) AS events FROM events GROUP BY source_id");
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
    const table = await screen.findByRole("table", { name: "Search results" });
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
