import { fromMore } from "./headerMenu";
import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";
import { setSql } from "./sqlEditor";

async function renderAt(path: string) {
  window.history.replaceState(null, "", path);
  window.localStorage.setItem("logs-tab", "sql");
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
  await screen.findByRole("heading", { name: "Logs", level: 1 });
  return spy;
}

function queries(spy: ReturnType<typeof mockApi>): string[] {
  return spy.mock.calls
    .filter(([u, init]) => String(u).endsWith("/api/query") && init?.method === "POST")
    .map(([, init]) => (JSON.parse(String(init?.body)) as { sql: string }).sql);
}

/** The search state, read from the fragment (never the query string). */
function addressQuery(): URLSearchParams {
  return new URLSearchParams(window.location.hash.replace(/^#/, ""));
}

afterEach(() => vi.restoreAllMocks());

describe("Search history (D90)", () => {
  it("records each run in the address, so Back returns to the previous search", async () => {
    const spy = await renderAt("/search");
    await waitFor(() => expect(addressQuery().get("tab")).toBe("sql"));
    await setSql("SELECT 1 AS first");
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 1 AS first"));
    await setSql("SELECT 2 AS second");
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 2 AS second"));
    expect(addressQuery().get("range")).toBe("24h");
    act(() => window.history.back());
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 1 AS first"));
    await waitFor(() => expect(queries(spy).at(-1)).toBe("SELECT 1 AS first"));
  });

  it("opens what a bookmarked or shared address says", async () => {
    const spy = await renderAt("/search#tab=sql&q=SELECT%2042%20AS%20shared&range=7d");
    await waitFor(() => expect(queries(spy)).toContain("SELECT 42 AS shared"));
    expect(
      within(screen.getByRole("group", { name: "Time" })).getByRole("button", { name: "7 days" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("search-state")).toHaveTextContent("Unsaved search");
  });

  it("opens a saved search by id with its parameter values", async () => {
    await renderAt("/search#saved=failed_by_ip&p.top=5&range=24h");
    await waitFor(() =>
      expect(screen.getByTestId("search-state")).toHaveTextContent("Open: Failed SSH by source"),
    );
    await waitFor(() => expect(addressQuery().get("saved")).toBe("failed_by_ip"));
    expect(addressQuery().get("p.top")).toBe("5");
  });
});

describe("New search (D90)", () => {
  it("asks before discarding unsaved edits, then starts over with the defaults", async () => {
    await renderAt("/search#tab=sql&q=SELECT%201&range=7d");
    await setSql("SELECT 99 AS not_run_yet");
    await userEvent.click(await fromMore("New search"));
    const ask = screen.getByRole("alertdialog", { name: "Discard unsaved edits" });
    expect(ask).toHaveTextContent("Your edits are not saved or run.");
    await userEvent.click(screen.getByRole("button", { name: "Discard and start new" }));
    await waitFor(() => expect(addressQuery().get("tab")).toBe("simple"));
    expect(addressQuery().get("range")).toBe("24h");
    expect(
      within(screen.getByRole("group", { name: "Time" })).getByRole("button", { name: "24 hours" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("search-state")).toHaveTextContent("Unsaved search");
  });

  it("starts over at once when nothing is unsaved", async () => {
    await renderAt("/search#tab=sql&q=SELECT%201&range=7d");
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 1"));
    await userEvent.click(await fromMore("New search"));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await waitFor(() => expect(addressQuery().get("tab")).toBe("simple"));
  });
});

describe("Recent searches (D90)", () => {
  it("lists the last runs under Open and jumps back to one", async () => {
    const spy = await renderAt("/search#tab=sql&q=SELECT%201%20AS%20older&range=7d");
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 1 AS older"));
    await setSql("SELECT 2 AS newer");
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 2 AS newer"));
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    const list = screen.getByRole("list", { name: "Recent searches" });
    const items = within(list).getAllByRole("button");
    expect(items[0]).toHaveTextContent("SELECT 2 AS newer");
    expect(items[1]).toHaveTextContent("SELECT 1 AS older");
    await userEvent.click(items[1]!);
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 1 AS older"));
    expect(
      within(screen.getByRole("group", { name: "Time" })).getByRole("button", { name: "7 days" }),
    ).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(queries(spy).at(-1)).toBe("SELECT 1 AS older"));
  });

  it("clears the list", async () => {
    await renderAt("/search#tab=sql&q=SELECT%201&range=24h");
    await waitFor(() => expect(addressQuery().get("q")).toBe("SELECT 1"));
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    await userEvent.click(screen.getByRole("button", { name: "Clear recent" }));
    expect(screen.queryByRole("list", { name: "Recent searches" })).toBeNull();
    expect(window.localStorage.getItem("search-recent")).toBeNull();
  });
});

describe("Search text stays out of server requests (D90)", () => {
  const secret = "SELECT 'alice.example' AS who, '198.51.100.77' AS addr";

  it("keeps the state in the fragment, which browsers never send", async () => {
    const spy = await renderAt("/search");
    await setSql(secret);
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(addressQuery().get("q")).toBe(secret));
    expect(window.location.search).toBe("");
    // What a reload, a bookmark, or a shared link sends: everything before the fragment.
    const sent = window.location.href.split("#")[0]!;
    for (const needle of ["alice", "198.51.100.77", "who"]) expect(sent).not.toContain(needle);
    // No request the page made carries the search text in its URL.
    for (const [u] of spy.mock.calls) {
      expect(String(u)).not.toContain("alice");
      expect(String(u)).not.toContain("198.51.100.77");
    }
  });

  it("moves an address from before the change out of the query string", async () => {
    const spy = await renderAt("/search?tab=sql&q=SELECT%207%20AS%20legacy&range=7d");
    await waitFor(() => expect(queries(spy)).toContain("SELECT 7 AS legacy"));
    expect(window.location.search).toBe("");
    expect(addressQuery().get("q")).toBe("SELECT 7 AS legacy");
    expect(
      within(screen.getByRole("group", { name: "Time" })).getByRole("button", { name: "7 days" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("rewrites recent searches kept before the change", async () => {
    window.history.replaceState(null, "", "/search");
    window.localStorage.setItem(
      "search-recent",
      JSON.stringify([
        { label: "SELECT 8", url: "/search?tab=sql&q=SELECT%208&range=24h", at: "" },
        { label: "SELECT 9", url: "/investigate/search#tab=sql&q=SELECT%209", at: "" },
      ]),
    );
    const { recentSearches } = await import("@/lib/searchUrl");
    expect(recentSearches()[0]!.url).toBe("/investigate/logs#tab=sql&q=SELECT%208&range=24h");
    // Kept before D206: the Logs address.
    expect(recentSearches()[1]!.url).toBe("/investigate/logs#tab=sql&q=SELECT%209");
  });
});

describe("The Logs time filter (ADR-0052 section 3.7; owner, 2026-11-13)", () => {
  const time = () => screen.getByRole("group", { name: "Time" });
  /** The time bounds of each query sent, newest last. */
  function bounds(spy: ReturnType<typeof mockApi>) {
    return spy.mock.calls
      .filter(([u, init]) => String(u).endsWith("/api/query") && init?.method === "POST")
      .map(([, init]) => JSON.parse(String(init?.body)) as { start?: string; end?: string });
  }

  it("has the five choices every page has: no 15 minutes, no All time", async () => {
    await renderAt("/search");
    expect(
      within(time())
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["1 hour", "24 hours", "7 days", "30 days", "Custom"]);
    expect(screen.queryByText(/All time|15 minutes/)).toBeNull();
    expect(within(time()).getByRole("button", { name: "24 hours" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("opens an old All time address as Custom with no dates, and 15 minutes as 1 hour", async () => {
    const spy = await renderAt("/search#tab=sql&q=SELECT%201%20AS%20old&range=all");
    await waitFor(() => expect(queries(spy)).toContain("SELECT 1 AS old"));
    expect(within(time()).getByRole("button", { name: "Custom" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByLabelText("From")).toHaveValue("");
    expect(screen.getByLabelText("To")).toHaveValue("");
    // Everything kept: no bound on either side, as All time ran.
    const last = bounds(spy).at(-1);
    expect(last?.start ?? null).toBeNull();
    expect(last?.end ?? null).toBeNull();

    const { searchUrl, readSearchUrl } = await import("@/lib/searchUrl");
    expect(readSearchUrl("#tab=sql&q=x&range=15m")?.range).toBe("1h");
    expect(readSearchUrl("#tab=sql&q=x&range=15m")?.custom).toBeUndefined();
    expect(
      readSearchUrl("#tab=sql&q=x&range=custom&from=2026-11-01T08:00&to=nope")?.custom,
    ).toEqual({ from: "2026-11-01T08:00", to: "" });
    // The address carries UTC times, so a link opens on the same moments in any time zone.
    const utc = new Date("2026-11-01T08:00").toISOString();
    const written = searchUrl({
      tab: "sql",
      q: "x",
      range: "24h",
      custom: { from: "2026-11-01T08:00", to: "" },
    });
    expect(written).toBe(
      `/investigate/logs#tab=sql&q=x&range=custom&from=${encodeURIComponent(utc)}`,
    );
    expect(readSearchUrl(written.slice(written.indexOf("#")))?.custom).toEqual({
      from: "2026-11-01T08:00",
      to: "",
    });
  });

  it("runs Custom between its two local date-times and keeps them in the address", async () => {
    const spy = await renderAt("/search");
    await userEvent.click(within(time()).getByRole("button", { name: "Custom" }));
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-11-01T08:00" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-11-02T08:00" } });
    await setSql("SELECT 5 AS windowed");
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(queries(spy).at(-1)).toBe("SELECT 5 AS windowed"));
    const sent = bounds(spy).at(-1);
    expect(sent?.start).toBe(new Date("2026-11-01T08:00").toISOString());
    // The end includes the minute it names.
    expect(sent?.end).toBe(new Date("2026-11-02T08:00:59.999").toISOString());
    await waitFor(() => expect(addressQuery().get("range")).toBe("custom"));
    expect(addressQuery().get("from")).toBe(new Date("2026-11-01T08:00").toISOString());
    expect(addressQuery().get("to")).toBe(new Date("2026-11-02T08:00").toISOString());
    // Pressing Custom again changes nothing: the dates stay.
    await userEvent.click(within(time()).getByRole("button", { name: "Custom" }));
    expect(screen.getByLabelText("From")).toHaveValue("2026-11-01T08:00");
    expect(screen.getByLabelText("To")).toHaveValue("2026-11-02T08:00");
    // A preset drops the dates.
    await userEvent.click(within(time()).getByRole("button", { name: "7 days" }));
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(addressQuery().get("range")).toBe("7d"));
    expect(addressQuery().get("from")).toBeNull();
    expect(bounds(spy).at(-1)?.end ?? null).toBeNull();
  });

  it("keeps the exact window another page handed over, through a reload, until a date is edited", async () => {
    const spy = await renderAt("/search");
    const { seedSearch } = await import("@/lib/searchSeed");
    const { navigate } = await import("@/lib/route");
    const exact = { from: "2026-11-06T08:00:00.250Z", to: "2026-11-06T09:00:00.000Z" };
    act(() => {
      seedSearch({ sql: "SELECT 9 AS drilled", window: exact });
      navigate("logs");
    });
    await waitFor(() => expect(queries(spy).at(-1)).toBe("SELECT 9 AS drilled"));
    // The bounds are the ones the number was counted over: nothing rounded, no minute added.
    expect(bounds(spy).at(-1)).toMatchObject({ start: exact.from, end: exact.to });
    expect(within(time()).getByRole("button", { name: "Custom" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // The address keeps them, so Reload, Back and a shared link open the same window.
    await waitFor(() => expect(addressQuery().get("exact")).toBe("1"));
    expect(addressQuery().get("from")).toBe(exact.from);
    expect(addressQuery().get("to")).toBe(exact.to);
    const { readSearchUrl } = await import("@/lib/searchUrl");
    expect(readSearchUrl()?.custom?.exact).toEqual(exact);
    // Editing a side makes it the person's own window.
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-11-06T10:00" } });
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() =>
      expect(bounds(spy).at(-1)?.end).toBe(new Date("2026-11-06T10:00:59.999").toISOString()),
    );
    await waitFor(() => expect(addressQuery().get("exact")).toBeNull());
  });
});
