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
  it("is the first tab and sends its values as bound parameters", async () => {
    const { spy } = await renderAt("/search");
    expect(await screen.findByRole("tab", { name: "Search", selected: true })).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Ask in plain English", pressed: false }),
    ).toBeVisible();
    await screen.findByText("Failed password for invalid user oracle");
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
    await renderAt("/search");
    await screen.findByText("Failed password for invalid user oracle");
    await userEvent.type(screen.getByLabelText("Search text"), "it's{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: "Edit as SQL" }));
    expect(screen.getByRole("tab", { name: "SQL", selected: true })).toBeVisible();
    expect(screen.getByLabelText("SQL query")).toHaveTextContent("ILIKE '%it''s%'");
  });

  it("shows why a search could not be read", async () => {
    await renderAt("/search");
    await screen.findByText("Failed password for invalid user oracle");
    await userEvent.type(screen.getByLabelText("Search text"), "(a{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("never closed");
  });

  it("filters for, filters out, and counts a field from an expanded event", async () => {
    const { spy } = await renderAt("/search");
    const row = (await screen.findByText("Failed password for invalid user oracle")).closest(
      "button",
    );
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
    const { spy } = await renderAt("/search");
    const row = (await screen.findByText("Failed password for invalid user oracle")).closest(
      "button",
    );
    await userEvent.click(row!);
    await screen.findByText("Raw event");
    expect(screen.queryByRole("button", { name: /Investigate linux_sshd/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Investigate bastion" }));
    await screen.findByRole("heading", { level: 1, name: "Investigations" });
    expect(window.location.pathname).toBe("/investigations");
    await screen.findByRole("group", { name: /Investigation lanes/ });
    const call = spy.mock.calls.find(([u]) => String(u).includes("/api/entities/graph"));
    expect(String(call?.[0])).toContain("kind=host");
    expect(String(call?.[0])).toContain("value=bastion");
  });

  it("remembers the tab last used", async () => {
    const { view } = await renderAt("/search");
    await userEvent.click(await screen.findByRole("tab", { name: "SQL" }));
    view.unmount();
    await renderAt("/search");
    expect(await screen.findByRole("tab", { name: "SQL", selected: true })).toBeVisible();
  });

  it("has no AI switch for auditors, and /ask opens Search with it on otherwise", async () => {
    const { view } = await renderAt("/ask", { mode: "login", signedIn: true, role: "auditor" });
    expect(await screen.findByRole("tab", { name: "Search", selected: true })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Ask in plain English" })).toBeNull();
    view.unmount();
    await renderAt("/ask");
    expect(await screen.findByRole("heading", { name: "Search", level: 1 })).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Ask in plain English", pressed: true }),
    ).toBeVisible();
    // Switching it off goes back to Simple syntax.
    await userEvent.click(
      screen.getByRole("button", { name: "Ask in plain English", pressed: true }),
    );
    expect(screen.getByLabelText("Search text")).toBeVisible();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByText("Search")).toHaveAttribute("aria-current", "page");
  });

  it("saves the compiled SQL with the Simple text as its origin", async () => {
    const { spy } = await renderAt("/search");
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
    await renderAt("/search");
    await screen.findByText("Failed password for invalid user oracle");
    await userEvent.type(screen.getByLabelText("Search text"), "-src_ip:203.0.113.9{Enter}");
    expect(
      await screen.findByText(/No event in this time range has a value in src_endpoint_ip/),
    ).toBeVisible();
  });

  it("fills the bar from a Suspicious preset and runs it", async () => {
    const { spy } = await renderAt("/search");
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
    const { spy } = await renderAt("/search");
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
});
