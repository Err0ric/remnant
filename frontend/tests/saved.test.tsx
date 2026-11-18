import { fromMore } from "./headerMenu";
import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";
import { setSql } from "./sqlEditor";
import { choose } from "./choose";

async function renderAt(
  path: string,
  auth: MockAuth = { mode: "login", signedIn: true, role: "analyst" },
) {
  window.history.replaceState(null, "", path);
  window.localStorage.setItem("logs-tab", "sql");
  const spy = mockApi("Codename", auth);
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
  return spy;
}

function bodies(spy: ReturnType<typeof mockApi>, test: (url: string) => boolean) {
  return spy.mock.calls
    .filter(([u, init]) => test(String(u)) && init?.method === "POST")
    .map(([, init]) => init?.body);
}

afterEach(() => vi.restoreAllMocks());

describe("Saving a search", () => {
  it("turns {{placeholders}} into typed parameters", async () => {
    const spy = await renderAt("/search");
    await screen.findByRole("heading", { name: "Logs", level: 1 });
    await setSql("SELECT * FROM events WHERE time > {{start}} LIMIT {{top}}");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const form = screen.getByRole("form", { name: "Save search" });
    await userEvent.type(within(form).getByLabelText("Name"), "Recent Events!");
    expect(within(form).getByText("Id: recent_events")).toBeInTheDocument();
    expect(within(form).queryByLabelText("Type of start")).not.toBeInTheDocument();
    await choose(within(form).getByLabelText("Type of top"), "int");
    await userEvent.type(within(form).getByLabelText("Default for top"), "5");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Saved as/)).toHaveTextContent(
      "Saved as Recent Events! recent_events",
    );
    expect(screen.getByRole("link", { name: "Open in Saved searches" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Schedule it" })).toBeInTheDocument();
    const sent = JSON.parse(String(bodies(spy, (u) => u.endsWith("/api/searches"))[0])) as {
      id: string;
      params: unknown[];
      visibility: string;
    };
    expect(sent.id).toBe("recent_events");
    expect(sent.visibility).toBe("private");
    expect(sent.params).toEqual([{ name: "top", type: "int", default: 5 }]);
  });

  it("is not offered to auditors", async () => {
    await renderAt("/search", { mode: "login", signedIn: true, role: "auditor" });
    await screen.findByRole("heading", { name: "Logs", level: 1 });
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  });
});

describe("Saved searches page", () => {
  it("shows the Ask question a search came from, as text", async () => {
    await renderAt("/saved");
    expect(
      await screen.findByText("From Ask AI: which IPs failed SSH the most?"),
    ).toBeInTheDocument();
  });

  it("runs a search with its default parameters", async () => {
    const spy = await renderAt("/saved");
    await userEvent.click(await screen.findByRole("button", { name: "Run Failed SSH by source" }));
    const runner = screen.getByRole("region", { name: "Run Failed SSH by source" });
    expect(within(runner).getByLabelText("top")).toHaveValue("25");
    await userEvent.click(within(runner).getByRole("button", { name: "Run" }));
    expect(await within(runner).findByText("203.0.113.9")).toBeInTheDocument();
    const sent = JSON.parse(String(bodies(spy, (u) => u.endsWith("/run"))[0])) as {
      params: Record<string, string>;
      start: string;
    };
    expect(sent.params).toEqual({ top: "25" });
    expect(sent.start).toBeTruthy();
  });

  it("only offers delete on your own searches unless you are an admin", async () => {
    await renderAt("/saved");
    await screen.findByText("Failed SSH by source");
    expect(
      screen.queryByRole("button", { name: "Delete Failed SSH by source" }),
    ).not.toBeInTheDocument();
  });

  it("lets admins delete after confirming", async () => {
    await renderAt("/saved", { mode: "login", signedIn: true, role: "admin" });
    await userEvent.click(
      await screen.findByRole("button", { name: "Delete Failed SSH by source" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByText("Failed SSH by source")).not.toBeInTheDocument());
  });

  it("imports a YAML file as a private search", async () => {
    const spy = await renderAt("/saved");
    await screen.findByText("Failed SSH by source");
    const input = screen.getByLabelText("Import file");
    await userEvent.upload(
      input,
      new File(["schema_version: 1\nid: x\n"], "x.yaml", { type: "application/yaml" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Imported imported_one as a private search",
    );
    const call = spy.mock.calls.find(([u]) => String(u).endsWith("/api/searches/import"));
    expect((call?.[1]?.headers as Record<string, string>)["Content-Type"]).toBe("application/yaml");
  });

  it("lets admins mark shared searches verified", async () => {
    await renderAt("/saved", { mode: "login", signedIn: true, role: "admin" });
    await userEvent.click(
      await screen.findByRole("button", { name: "Verify Failed SSH by source" }),
    );
    expect(await screen.findByText("Verified")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Unverify Failed SSH by source" }),
    ).toBeInTheDocument();
  });

  it("does not offer verification to analysts", async () => {
    await renderAt("/saved");
    await screen.findByRole("button", { name: "Run Failed SSH by source" });
    expect(screen.queryByRole("button", { name: /^Verify/ })).not.toBeInTheDocument();
  });

  it("opens a saved search on the Search page, fills its parameters, and saves changes", async () => {
    const spy = await renderAt("/search");
    await screen.findByRole("heading", { name: "Logs", level: 1 });
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    const panel = await screen.findByRole("region", { name: "Open a saved search" });
    await userEvent.type(within(panel).getByLabelText("Open a saved search"), "ssh");
    await userEvent.click(within(panel).getByRole("button", { name: /Failed SSH by source/ }));
    expect(await screen.findByText(/Open:/)).toHaveTextContent("Failed SSH by source");
    // The default (25) fills {{top}} and the query runs at once.
    await waitFor(() => {
      const runs = bodies(spy, (u) => u.endsWith("/api/query")).map(
        (b) => JSON.parse(String(b)) as { sql: string; params?: Record<string, unknown> },
      );
      expect(runs.some((r) => r.sql === "SELECT 1 LIMIT {{top}}" && r.params?.top === 25)).toBe(
        true,
      );
    });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const form = await screen.findByRole("form", { name: "Save search" });
    expect(within(form).getByRole("heading")).toHaveTextContent(
      "Save changes to Failed SSH by source",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(
        spy.mock.calls.some(
          ([u, i]) => String(u).endsWith("/api/searches/failed_by_ip") && i?.method === "PUT",
        ),
      ).toBe(true),
    );
  });

  it("offers to move SQL typed into the Simple box", async () => {
    window.localStorage.setItem("logs-tab", "simple");
    window.history.replaceState(null, "", "/search");
    mockApi("Codename", { mode: "login", signedIn: true, role: "analyst" });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    render(<App initialTheme="dark" queryClient={new QueryClient()} />);
    const box = await screen.findByLabelText("Search text");
    await userEvent.type(box, "SELECT count(*) FROM events");
    await userEvent.click(await screen.findByRole("button", { name: "Run it in SQL mode" }));
    expect(await screen.findByLabelText("SQL query")).toHaveTextContent(
      "SELECT count(*) FROM events",
    );
  });
});

describe("Edit (F37)", () => {
  it("opens your own saved search in Logs to change and save it", async () => {
    window.history.replaceState(null, "", "/saved");
    window.localStorage.setItem("logs-tab", "sql");
    const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "analyst" });
    const real = spy.getMockImplementation();
    const mine = {
      id: "my_search",
      name: "My search",
      description: "",
      tags: [],
      visibility: "private",
      sources: null,
      sql: "SELECT 1",
      params: [],
      mode: "query",
      owner_id: "u1",
      verified: false,
      created_at: "2026-10-10T10:00:00Z",
      updated_at: "2026-10-10T10:00:00Z",
    };
    spy.mockImplementation((url, init) =>
      String(url).endsWith("/api/searches") && (init?.method ?? "GET") === "GET"
        ? Promise.resolve(
            new Response(JSON.stringify([mine]), {
              headers: { "Content-Type": "application/json" },
            }),
          )
        : (real as typeof fetch)(url, init),
    );
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    render(<App initialTheme="dark" queryClient={new QueryClient()} />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit My search" }));
    await waitFor(() => expect(window.location.pathname).toBe("/investigate/logs"));
    expect(await screen.findByText("Save changes to My search")).toBeInTheDocument();
  });

  it("is not offered on someone else's search", async () => {
    await renderAt("/saved");
    await screen.findByRole("button", { name: "Run Failed SSH by source" });
    expect(screen.queryByRole("button", { name: "Edit Failed SSH by source" })).toBeNull();
  });
});

describe("Add to dashboard (D89)", () => {
  function calls(spy: ReturnType<typeof mockApi>, method: string, test: (u: string) => boolean) {
    return spy.mock.calls
      .filter(([u, init]) => test(String(u)) && init?.method === method)
      .map(([, init]) => JSON.parse(String(init?.body ?? "null")) as unknown);
  }

  it("saves a label-and-count result, then adds it hourly over 24 hours as bars", async () => {
    const spy = await renderAt("/search");
    await screen.findByRole("heading", { name: "Logs", level: 1 });
    await setSql("SELECT source_id, count(*) AS events FROM events GROUP BY source_id");
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    await screen.findAllByText("paloalto_traffic");
    await userEvent.click(await fromMore("Add to dashboard"));
    const form = screen.getByRole("form", { name: "Save search" });
    await userEvent.type(within(form).getByLabelText("Name"), "Top sources");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    const panel = await screen.findByRole("form", { name: "Add to dashboard" });
    expect(panel).toHaveTextContent("Hourly, last 24 hours, bars, a third wide, private.");
    await userEvent.click(within(panel).getByRole("button", { name: "Add to dashboard" }));
    await waitFor(() => expect(window.location.pathname).toBe("/dashboard"));
    expect(calls(spy, "POST", (u) => u.endsWith("/api/schedules"))).toEqual([
      {
        kind: "search",
        target_id: "top_sources",
        name: "Top sources",
        cron: "hourly",
        lookback_minutes: 1440,
        shared: false,
        panel_view: "bars",
      },
    ]);
    expect(spy.mock.calls.some(([u]) => /\/api\/schedules\/[^/]+\/run$/.test(String(u)))).toBe(
      true,
    );
  });

  it("adds a saved search from Saved searches", async () => {
    const spy = await renderAt("/saved");
    await userEvent.click(
      await screen.findByRole("button", { name: "Add Failed SSH by source to dashboard" }),
    );
    const panel = screen.getByRole("form", { name: "Add to dashboard" });
    expect(panel).toHaveTextContent("Hourly, last 24 hours, table, a third wide, private.");
    await userEvent.click(within(panel).getByRole("button", { name: "Add to dashboard" }));
    await waitFor(() => expect(window.location.pathname).toBe("/dashboard"));
    expect(calls(spy, "POST", (u) => u.endsWith("/api/schedules"))).toHaveLength(1);
  });
});

describe("Saved searches under Logs (ADR-0052 section 3.3, redesign build row 8)", () => {
  it("is a tab of Logs, not a rail entry, and the old address lands on it", async () => {
    await renderAt("/saved");
    await waitFor(() => expect(window.location.pathname).toBe("/investigate/saved"));
    expect(await screen.findByRole("heading", { name: "Logs", level: 1 })).toBeVisible();
    const tabs = screen.getByRole("navigation", { name: "Logs tabs" });
    expect(within(tabs).getByRole("link", { name: "Saved searches" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    const rail = screen.getByRole("navigation", { name: "Primary" });
    // Not a rail entry: only a tab row under the current page, Logs (D268).
    expect(rail.querySelector('[data-rail-entry="saved"]')).toBeNull();
    expect(
      within(within(rail).getByRole("list", { name: "Logs tabs" })).getByRole("link", {
        name: "Saved searches",
      }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("points to the Library, a tab of the same page (owner, 2026-11-17)", async () => {
    await renderAt("/investigate/saved");
    await screen.findByRole("table", { name: "Saved searches" });
    const line = screen.getByText(/Start from a tested query in the/);
    const link = within(line).getByRole("link", { name: "Library" });
    expect(link).toHaveAttribute("href", "/investigate/library");
    await userEvent.click(link);
    expect(window.location.pathname).toBe("/investigate/library");
  });

  it("has no Library pointer for an Auditor without SQL, who has no Library", async () => {
    await renderAt("/investigate/saved", { mode: "login", signedIn: true, role: "auditor" });
    await screen.findByRole("table", { name: "Saved searches" });
    expect(screen.queryByText(/Start from a tested query/)).toBeNull();
  });

  it("says which searches are scheduled, and the link opens that schedule", async () => {
    await renderAt("/investigate/saved");
    const table = await screen.findByRole("table", { name: "Saved searches" });
    expect(within(table).getByRole("columnheader", { name: "Scheduled" })).toBeVisible();
    const row = (await within(table).findByText("failed_by_ip")).closest("tr") as HTMLElement;
    const link = await within(row).findByRole("link", { name: "Daily at 07:00" });
    expect(link).toHaveAttribute("href", "/alerts/schedules#item=s1");
    await userEvent.click(link);
    expect(window.location.pathname + window.location.hash).toBe("/alerts/schedules#item=s1");
    const schedules = await screen.findByRole("table", { name: "Schedules" });
    const marked = await waitFor(() => {
      const tr = schedules.querySelector("tr[aria-current]");
      expect(tr).not.toBeNull();
      return tr as HTMLElement;
    });
    expect(marked).toHaveTextContent("Failed SSH daily");
    expect(schedules.querySelectorAll("tr[aria-current]")).toHaveLength(1);
  });

  async function renderWithSchedules(reply: () => Response) {
    window.history.replaceState(null, "", "/investigate/saved");
    const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "analyst" });
    const real = spy.getMockImplementation() as typeof fetch;
    spy.mockImplementation(async (url, init) =>
      String(url).endsWith("/api/schedules") && (init?.method ?? "GET") === "GET"
        ? reply()
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
    const table = await screen.findByRole("table", { name: "Saved searches" });
    return (await within(table).findByText("failed_by_ip")).closest("tr") as HTMLElement;
  }
  const jsonReply = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });

  it("says No only when the schedules loaded and none runs the search", async () => {
    const row = await renderWithSchedules(() => jsonReply([]));
    expect(await within(row).findByText("No")).toBeVisible();
  });

  it("does not say No when the schedules could not be read", async () => {
    const row = await renderWithSchedules(() =>
      jsonReply({ error: { code: "internal", message: "boom" } }, 500),
    );
    expect(await within(row).findByText("Could not load")).toBeVisible();
    expect(within(row).queryByText("No")).toBeNull();
  });

  it("marks a paused schedule, and scrolls to the linked one on Schedules", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const row = await renderWithSchedules(() =>
      jsonReply([
        {
          schedule_id: "p1",
          kind: "search",
          target_id: "failed_by_ip",
          name: "Paused one",
          owner_id: "u1",
          mine: true,
          shared: false,
          cron: "0 * * * *",
          lookback_minutes: 60,
          params: {},
          threshold_kind: null,
          threshold_value: null,
          paused: true,
          paused_reason: null,
          recent: [],
          target_ids: [],
        },
      ]),
    );
    const link = await within(row).findByRole("link", { name: "Hourly" });
    expect(link.closest("li")).toHaveTextContent("Hourly (paused)");
    await userEvent.click(link);
    const schedules = await screen.findByRole("table", { name: "Schedules" });
    await waitFor(() => expect(schedules.querySelector("tr[aria-current]")).not.toBeNull());
    await waitFor(() => expect(scroll).toHaveBeenCalled());
    expect(scroll.mock.instances[0]).toBe(schedules.querySelector("tr[aria-current]"));
  });
});
