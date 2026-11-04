import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

async function renderAt(path: string, auth: MockAuth = { mode: "open" }) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", auth);
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(<App initialTheme="dark" queryClient={client} />);
  return { spy, view };
}

type Body = { sql?: string; params?: Record<string, unknown>; text?: string; top?: string };
function posts(spy: ReturnType<typeof mockApi>, suffix: string): Body[] {
  return spy.mock.calls
    .filter(([u, init]) => String(u).endsWith(suffix) && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)) as Body);
}

afterEach(() => vi.restoreAllMocks());

describe("Simple search", () => {
  it("loads the SQL editor only when the SQL tab is opened", async () => {
    await renderAt("/investigate/logs");
    expect(await screen.findByRole("heading", { name: "Investigate", level: 1 })).toBeVisible();
    expect(screen.queryByLabelText("SQL query")).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "SQL" }));
    expect(await screen.findByLabelText("SQL query")).toBeInTheDocument();
  });

  it("is the first tab and sends its values as bound parameters", async () => {
    const { spy } = await renderAt("/investigate/logs");
    expect(await screen.findByRole("heading", { name: "Investigate", level: 1 })).toBeVisible();
    expect(screen.getByRole("tab", { name: "Filters", selected: true })).toBeVisible();
    expect(screen.queryByRole("tab", { name: "Ask AI" })).toBeNull();
    await screen.findByText("Failed password for invalid user oracle");
    // The submit button runs the filters (owner, 2026-11-04): "Run", not "Search".
    expect(screen.getByRole("button", { name: "Run" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Search" })).toBeNull();
    await userEvent.type(screen.getByLabelText("Search text"), "oracle{Enter}");
    await vi.waitFor(() => expect(posts(spy, "/api/search/compile").at(-1)?.text).toBe("oracle"));
    await vi.waitFor(() =>
      expect(posts(spy, "/api/query").at(-1)?.params).toEqual({ p0: "%oracle%" }),
    );
    expect(posts(spy, "/api/query").at(-1)?.sql).toContain("ILIKE $p0");
    await userEvent.click(screen.getByRole("button", { name: "Show SQL" }));
    expect(screen.getByLabelText("SQL for this search")).toHaveTextContent('$p0 = "%oracle%"');
  });

  it("opens the search in the SQL tab with the values written in", async () => {
    await renderAt("/investigate/logs");
    await screen.findByText("Failed password for invalid user oracle");
    await userEvent.type(screen.getByLabelText("Search text"), "it's{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: "Edit as SQL" }));
    expect(screen.getByRole("tab", { name: "SQL", selected: true })).toBeVisible();
    expect(await screen.findByLabelText("SQL query")).toHaveTextContent("ILIKE '%it''s%'");
  });

  it("shows why a search could not be read", async () => {
    await renderAt("/investigate/logs");
    await screen.findByText("Failed password for invalid user oracle");
    await userEvent.type(screen.getByLabelText("Search text"), "(a{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("never closed");
  });

  it("filters for, filters out, and counts a field from an expanded event", async () => {
    const { spy } = await renderAt("/investigate/logs");
    const row = (await screen.findByText("Failed password for invalid user oracle")).closest(
      '[role="row"]',
    ) as HTMLElement | null;
    await userEvent.click(row!);
    await screen.findByText("Raw event");
    await userEvent.click(screen.getByRole("button", { name: "Filter for device_hostname" }));
    await vi.waitFor(() =>
      expect(posts(spy, "/api/search/compile").at(-1)?.text).toBe('device_hostname:"bastion"'),
    );
    expect(screen.getByLabelText("Search text")).toHaveValue('device_hostname:"bastion"');
    await userEvent.click(await screen.findByText("Failed password for invalid user oracle"));
    await screen.findByText("Raw event");
    await userEvent.click(screen.getByRole("button", { name: "Filter out source_id" }));
    await vi.waitFor(() =>
      expect(posts(spy, "/api/search/compile").at(-1)?.text).toBe(
        'device_hostname:"bastion" -source_id:"linux_sshd"',
      ),
    );
    await userEvent.click(await screen.findByText("Failed password for invalid user oracle"));
    await screen.findByText("Raw event");
    await userEvent.click(screen.getByRole("button", { name: "Top values of source_id" }));
    await vi.waitFor(() => expect(posts(spy, "/api/search/compile").at(-1)?.top).toBe("source_id"));
    expect(screen.queryByRole("button", { name: "Filter for raw" })).toBeNull();
  });

  it("opens Investigations on a host from an expanded event", async () => {
    const { spy } = await renderAt("/investigate/logs");
    const row = (await screen.findByText("Failed password for invalid user oracle")).closest(
      '[role="row"]',
    ) as HTMLElement | null;
    await userEvent.click(row!);
    await screen.findByText("Raw event");
    // The value itself is the link (product pass step 2); a source id is not an entity.
    expect(screen.queryByRole("link", { name: "linux_sshd" })).toBeNull();
    const detail = screen.getByText("Raw event").closest("div")?.parentElement
      ?.parentElement as HTMLElement;
    const host = within(detail).getAllByRole("link", { name: "bastion" })[0] as HTMLElement;
    expect(host).toHaveAttribute("href", "/investigate/people#host=bastion");
    await userEvent.click(host);
    await screen.findByRole("heading", { level: 1, name: "Investigate" });
    expect(window.location.pathname + window.location.hash).toBe(
      "/investigate/people#host=bastion",
    );
    await screen.findByRole("group", { name: /Investigation lanes/ });
    const call = spy.mock.calls.find(([u]) => String(u).includes("/api/entities/graph"));
    expect(String(call?.[0])).toContain("kind=host");
    expect(String(call?.[0])).toContain("value=bastion");
  });

  it("remembers the tab last used", async () => {
    const { view } = await renderAt("/investigate/logs");
    await userEvent.click(await screen.findByRole("tab", { name: "SQL" }));
    view.unmount();
    await renderAt("/investigate/logs");
    expect(await screen.findByRole("tab", { name: "SQL", selected: true })).toBeVisible();
  });

  it("opens Filters when the browser last used the former Ask tab (D206)", async () => {
    window.localStorage.setItem("search-tab", "ask");
    await renderAt("/investigate/logs");
    expect(await screen.findByRole("tab", { name: "Filters", selected: true })).toBeVisible();
    expect(window.location.pathname).toBe("/investigate/logs");
  });

  it("has exactly the Filters and SQL modes; Ask AI is its own page (D206)", async () => {
    const { view } = await renderAt("/investigate/logs");
    const modes = await screen.findByRole("tablist", { name: "Logs mode" });
    expect(
      within(modes)
        .getAllByRole("tab")
        .map((t) => t.textContent),
    ).toEqual(["Filters", "SQL"]);
    expect(screen.queryByLabelText("Question")).toBeNull();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: "Logs" })).toHaveAttribute("aria-current", "page");
    // The rail's Ask AI opens its own page.
    await userEvent.click(within(nav).getByRole("link", { name: "Ask AI" }));
    expect(window.location.pathname).toBe("/ask-ai");
    expect(await screen.findByLabelText("Question")).toBeVisible();
    expect(screen.queryByRole("tablist", { name: "Logs mode" })).toBeNull();
    expect(within(nav).getByRole("link", { name: "Ask AI" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    view.unmount();
    // Auditors have no Ask AI: no rail row, no header tab, and /ask-ai lands on Logs.
    await renderAt("/ask-ai", { mode: "login", signedIn: true, role: "auditor" });
    expect(await screen.findByRole("tab", { name: "Filters", selected: true })).toBeVisible();
    await vi.waitFor(() => expect(window.location.pathname).toBe("/investigate/logs"));
    const audNav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(audNav).queryByRole("link", { name: "Ask AI" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Ask AI" })).toBeNull(); // nor in the header tabs
  });

  it("saves the compiled SQL with the Simple text as its origin", async () => {
    const { spy } = await renderAt("/investigate/logs");
    await screen.findByText("Failed password for invalid user oracle");
    await userEvent.type(screen.getByLabelText("Search text"), "oracle{Enter}");
    await vi.waitFor(() => expect(posts(spy, "/api/query").at(-1)?.params).toBeTruthy());
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const form = screen.getByRole("form", { name: "Save search" });
    await userEvent.type(within(form).getByLabelText("Name"), "Oracle lines");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await screen.findByRole("status");
    const saved = posts(spy, "/api/searches").at(-1) as Body & { origin?: unknown };
    expect(saved.sql).toContain("ILIKE '%oracle%'");
    expect(saved.origin).toEqual({ simple_text: "oracle" });
  });

  it("says when a filtered field is empty in the time range", async () => {
    await renderAt("/investigate/logs");
    await screen.findByText("Failed password for invalid user oracle");
    await userEvent.type(screen.getByLabelText("Search text"), "-src_ip:203.0.113.9{Enter}");
    expect(
      await screen.findByText(/No event in this time range has a value in src_endpoint_ip/),
    ).toBeVisible();
  });

  it("fills the bar from a Suspicious preset and runs it", async () => {
    const { spy } = await renderAt("/investigate/logs");
    await screen.findByText("Failed password for invalid user oracle");
    await userEvent.selectOptions(
      await screen.findByLabelText("Suspicious activity presets"),
      "failed_signins",
    );
    expect(screen.getByLabelText("Search text")).toHaveValue('EventID:4625 OR "failed password"');
    await vi.waitFor(() =>
      expect(posts(spy, "/api/search/compile").at(-1)?.text).toBe(
        'EventID:4625 OR "failed password"',
      ),
    );
  });

  it("counts fields for the whole result and filters from a click", async () => {
    const { spy } = await renderAt("/investigate/logs");
    await screen.findByText("Failed password for invalid user oracle");
    const fields = await screen.findByRole("complementary", { name: "Fields" });
    const ips = await within(fields).findByRole("region", { name: /source ip/i });
    expect(within(ips).getByText("40")).toBeVisible();
    await userEvent.click(within(ips).getByRole("button", { name: /^203\.0\.113\.9/ }));
    await vi.waitFor(() =>
      expect(posts(spy, "/api/search/compile").at(-1)?.text).toBe('src_ip:"203.0.113.9"'),
    );
    await userEvent.click(within(ips).getByRole("button", { name: "Exclude (no value)" }));
    await vi.waitFor(() =>
      expect(posts(spy, "/api/search/compile").at(-1)?.text).toBe('src_ip:"203.0.113.9" src_ip:*'),
    );
    const facetBodies = () =>
      spy.mock.calls
        .filter(([u]) => String(u).endsWith("/api/search/facets"))
        .map(([, init]) => JSON.parse(String(init?.body)) as { text?: string });
    await vi.waitFor(() =>
      expect(facetBodies().at(-1)?.text).toBe('src_ip:"203.0.113.9" src_ip:*'),
    );
  });

  it("in SQL mode, a field click adds the filter to the SQL and runs it", async () => {
    const { spy } = await renderAt("/investigate/logs");
    await screen.findByText("Failed password for invalid user oracle");
    await userEvent.click(screen.getByRole("tab", { name: "SQL" }));
    await userEvent.click(screen.getByRole("button", { name: "Run query" }));
    const fields = await screen.findByRole("complementary", { name: "Fields" });
    expect(await within(fields).findByText("click to filter")).toBeVisible();
    const src = await within(fields).findByRole("region", { name: /^source$/i });
    await userEvent.click(within(src).getByRole("button", { name: /^linux_sshd/ }));
    await vi.waitFor(() =>
      expect(posts(spy, "/api/query").at(-1)?.sql).toMatch(/WHERE source_id = 'linux_sshd'$/),
    );
    const refine = posts(spy, "/api/query/refine").at(-1) as Body & { field?: string };
    expect(refine.field).toBe("source_id");
  });
});
