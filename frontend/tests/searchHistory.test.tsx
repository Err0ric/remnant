import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";
import { setSql } from "./sqlEditor";

async function renderAt(path: string) {
  window.history.replaceState(null, "", path);
  window.localStorage.setItem("search-tab", "sql");
  window.localStorage.removeItem("search-recent");
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "analyst" });
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
  await screen.findByRole("heading", { name: "Search", level: 1 });
  return spy;
}

function queries(spy: ReturnType<typeof mockApi>): string[] {
  return spy.mock.calls
    .filter(([u, init]) => String(u).endsWith("/api/query") && init?.method === "POST")
    .map(([, init]) => (JSON.parse(String(init?.body)) as { sql: string }).sql);
}

function addressQuery(): URLSearchParams {
  return new URLSearchParams(window.location.search);
}

afterEach(() => vi.restoreAllMocks());

describe("Search history (D90)", () => {
  it("records each run in the address, so Back returns to the previous search", async () => {
    const spy = await renderAt("/search");
    await waitFor(() => expect(addressQuery().get("tab")).toBe("sql"));
    await setSql("SELECT 1 AS first");
    await userEvent.click(screen.getByRole("button", { name: "Run query" }));
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 1 AS first"));
    await setSql("SELECT 2 AS second");
    await userEvent.click(screen.getByRole("button", { name: "Run query" }));
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 2 AS second"));
    expect(addressQuery().get("range")).toBe("24h");
    act(() => window.history.back());
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 1 AS first"));
    await waitFor(() => expect(queries(spy).at(-1)).toBe("SELECT 1 AS first"));
  });

  it("opens what a bookmarked or shared address says", async () => {
    const spy = await renderAt("/search?tab=sql&q=SELECT%2042%20AS%20shared&range=7d");
    await waitFor(() => expect(queries(spy)).toContain("SELECT 42 AS shared"));
    expect(screen.getByLabelText("Time range")).toHaveValue("7d");
    expect(screen.getByTestId("search-state")).toHaveTextContent("Unsaved search");
  });

  it("opens a saved search by id with its parameter values", async () => {
    await renderAt("/search?saved=failed_by_ip&p.top=5&range=24h");
    await waitFor(() =>
      expect(screen.getByTestId("search-state")).toHaveTextContent("Open: Failed SSH by source"),
    );
    await waitFor(() => expect(addressQuery().get("saved")).toBe("failed_by_ip"));
    expect(addressQuery().get("p.top")).toBe("5");
  });
});

describe("New search (D90)", () => {
  it("asks before discarding unsaved edits, then starts over with the defaults", async () => {
    await renderAt("/search?tab=sql&q=SELECT%201&range=7d");
    await setSql("SELECT 99 AS not_run_yet");
    await userEvent.click(screen.getByRole("button", { name: "New search" }));
    const ask = screen.getByRole("alertdialog", { name: "Discard unsaved edits" });
    expect(ask).toHaveTextContent("Your edits are not saved or run.");
    await userEvent.click(screen.getByRole("button", { name: "Discard and start new" }));
    await waitFor(() => expect(addressQuery().get("tab")).toBe("simple"));
    expect(addressQuery().get("range")).toBe("24h");
    expect(screen.getByLabelText("Time range")).toHaveValue("24h");
    expect(screen.getByTestId("search-state")).toHaveTextContent("Unsaved search");
  });

  it("starts over at once when nothing is unsaved", async () => {
    await renderAt("/search?tab=sql&q=SELECT%201&range=7d");
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 1"));
    await userEvent.click(screen.getByRole("button", { name: "New search" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await waitFor(() => expect(addressQuery().get("tab")).toBe("simple"));
  });
});

describe("Recent searches (D90)", () => {
  it("lists the last runs under Open and jumps back to one", async () => {
    const spy = await renderAt("/search?tab=sql&q=SELECT%201%20AS%20older&range=7d");
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 1 AS older"));
    await setSql("SELECT 2 AS newer");
    await userEvent.click(screen.getByRole("button", { name: "Run query" }));
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 2 AS newer"));
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    const list = screen.getByRole("list", { name: "Recent searches" });
    const items = within(list).getAllByRole("button");
    expect(items[0]).toHaveTextContent("SELECT 2 AS newer");
    expect(items[1]).toHaveTextContent("SELECT 1 AS older");
    await userEvent.click(items[1]!);
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 1 AS older"));
    expect(screen.getByLabelText("Time range")).toHaveValue("7d");
    await waitFor(() => expect(queries(spy).at(-1)).toBe("SELECT 1 AS older"));
  });

  it("clears the list", async () => {
    await renderAt("/search?tab=sql&q=SELECT%201&range=24h");
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 1"));
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    await userEvent.click(screen.getByRole("button", { name: "Clear recent" }));
    expect(screen.queryByRole("list", { name: "Recent searches" })).toBeNull();
    expect(window.localStorage.getItem("search-recent")).toBeNull();
  });
});
