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
    // Five groups (owner 2026-10-31); Investigate lists its pages as rows.
    const groups = within(nav)
      .getAllByRole("region")
      .map((g) => g.getAttribute("aria-label"));
    expect(groups).toEqual(["Monitor", "Investigate", "AI", "Connected apps", "System"]);
    const rows = (name: string) =>
      Array.from(within(within(nav).getByRole("region", { name })).getAllByRole("listitem"))
        .filter((li) => li.parentElement?.id === `rail-${name.toLowerCase()}`)
        .map((li) => li.querySelector("a")?.textContent);
    expect(rows("Monitor")).toEqual(["Dashboard", "Alerts"]);
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

  it("opens a page's sub-pages on hover only in the icon rail (owner, 2026-11-01)", async () => {
    const icon = "(min-width: 768px) and (max-width: 1099.98px)";
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: q === icon,
      media: q,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }));
    try {
      await renderApp();
      const nav = screen.getByRole("navigation", { name: "Primary" });
      await userEvent.hover(within(nav).getByRole("link", { name: /^Alerts/ }));
      const menu = await screen.findByRole("list", { name: "Alerts pages, Alerts menu" });
      expect(within(menu).getByRole("link", { name: "Rules" })).toHaveAttribute(
        "href",
        "/alerts/rules",
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("lists every page's sub-pages and folds groups, remembered (ADR-0038 edit 10)", async () => {
    window.localStorage.removeItem("app.rail.collapsed");
    window.localStorage.removeItem("app.rail.defaults");
    await renderApp();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    // Every page with sub-pages lists them, not only the open one; Alerts starts folded
    // (its row shows the open count). In the labelled rail nothing opens on hover.
    const fold = within(nav).getByRole("button", { name: "Alerts sub-pages" });
    expect(fold).toHaveAttribute("aria-expanded", "false");
    expect(within(nav).getByRole("list", { name: "Alerts pages" })).not.toHaveClass(
      "min-[1100px]:block",
    );
    await userEvent.hover(within(nav).getByRole("link", { name: /^Alerts/ }));
    expect(screen.queryByRole("list", { name: "Alerts pages, Alerts menu" })).toBeNull();
    await userEvent.click(fold);
    expect(fold).toHaveAttribute("aria-expanded", "true");
    expect(within(nav).getByRole("list", { name: "Alerts pages" })).toHaveClass(
      "min-[1100px]:block",
    );
    expect(within(nav).getByRole("list", { name: "Agents pages" })).toHaveTextContent(
      "OverviewSessionsToolsMCP serversAccounts",
    );
    // Connected apps and System start folded, once; then the viewer's choice holds.
    const connected = within(nav).getByRole("button", { name: "Connected apps group" });
    const system = within(nav).getByRole("button", { name: "System group" });
    expect(connected).toHaveAttribute("aria-expanded", "false");
    expect(system).toHaveAttribute("aria-expanded", "false");
    // Owner, 2026-11-01: a folded group header opens inline on click only; hovering it
    // shows no flyout (one behavior per control).
    await userEvent.hover(connected);
    await userEvent.hover(system);
    expect(screen.queryByRole("list", { name: /menu$/ })).toBeNull();
    expect(connected).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(system);
    expect(system).toHaveAttribute("aria-expanded", "true");
    expect(JSON.parse(window.localStorage.getItem("app.rail.collapsed") ?? "[]")).toEqual([
      "connected",
    ]);
    // Reloading keeps it: the default is applied once.
    expect(JSON.parse(window.localStorage.getItem("app.rail.defaults") ?? "[]")).toEqual([
      "connected",
      "system",
      "area:alerts",
    ]);
    window.localStorage.removeItem("app.rail.collapsed");
    window.localStorage.removeItem("app.rail.defaults");
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
    await userEvent.click(within(box).getByRole("button", { name: "Open in Search" }));
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

describe("Query library (ADR-0033)", () => {
  it("loads a query into the SQL tab with why and normal, saves a copy, and replaces one", async () => {
    const spy = await renderApp();
    await userEvent.click(screen.getByRole("button", { name: "Library" }));
    const lib = await screen.findByRole("region", { name: "Query library" });
    expect(await within(lib).findByText("Linux / SSH")).toBeVisible();
    expect(
      within(lib).getByText("12 more queries need sources you do not have events from."),
    ).toBeVisible();
    await userEvent.click(
      within(lib).getByRole("button", { name: "Save SSH logins by user and source as my own" }),
    );
    expect(
      spy.mock.calls.some(
        ([u, i]) =>
          String(u).endsWith("/api/library/linux_auth/ssh_logins/copy") && i?.method === "POST",
      ),
    ).toBe(true);
    await userEvent.click(within(lib).getByRole("button", { name: "Updated in this version" }));
    expect(within(lib).getByLabelText("Changes to sudo refused")).toHaveTextContent("- SELECT 1");
    await userEvent.click(within(lib).getByRole("button", { name: "Replace my copy" }));
    expect(
      spy.mock.calls.some(([u]) =>
        String(u).endsWith("/api/library/linux_auth/sudo_denied/replace"),
      ),
    ).toBe(true);
    await userEvent.click(
      within(lib).getByRole("button", { name: "SSH logins by user and source" }),
    );
    const note = await screen.findByRole("note", { name: "From the query library" });
    expect(note).toHaveTextContent("Why SSH logins by user and source");
    expect(note).toHaveTextContent("Normal: Normal for SSH logins by user and source");
    expect(screen.queryByRole("region", { name: "Query library" })).toBeNull();
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
