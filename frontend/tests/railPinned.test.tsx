import { QueryClient } from "@tanstack/react-query";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

/** D259: the rail's Pinned, the viewer's pinned saved searches and dashboards. */
let client: QueryClient;

async function rail(path: string, auth: MockAuth) {
  window.history.replaceState(null, "", path);
  mockApi("Codename", auth);
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
  return screen.findByRole("navigation", { name: "Primary" });
}

const ADMIN: MockAuth = { mode: "login", signedIn: true, role: "admin" };
const SEARCH = { kind: "search" as const, id: "failed_by_ip", name: "Failed SSH by source" };
const BOARD = { kind: "dashboard" as const, id: "d2", name: "Team" };
/** Dashboards d3 to d5 beside the two the mock has, so five pins all have targets. */
async function threeMoreBoards() {
  for (const n of [3, 4, 5])
    await fetch("/api/dashboards", {
      method: "POST",
      body: JSON.stringify({ name: `Board ${n}` }),
    });
  await act(() => client.invalidateQueries({ queryKey: ["pins"] }));
}

const pinned = () =>
  within(screen.getByRole("navigation", { name: "Pinned" }))
    .getAllByRole("link")
    .map((a) => a.textContent);

afterEach(() => window.history.replaceState(null, "", "/"));

describe("Rail Pinned (D259)", () => {
  it("is hidden with no pins", async () => {
    await rail("/alerts", ADMIN);
    await screen.findByRole("heading", { level: 1, name: "Alerts" });
    expect(screen.queryByRole("navigation", { name: "Pinned" })).toBeNull();
  });

  it("lists the pins in their own region, oldest first, each opening its target", async () => {
    const nav = await rail("/alerts", { ...ADMIN, pins: [SEARCH, BOARD] });
    const region = await screen.findByRole("navigation", { name: "Pinned" });
    expect(pinned()).toEqual(["Failed SSH by source", "Team"]);
    const search = within(region).getByRole("link", { name: "Failed SSH by source" });
    expect(search).toHaveAttribute("href", "/investigate/saved#open=failed_by_ip");
    expect(search).toHaveAttribute("title", "Saved search: Failed SSH by source");
    expect(search).toHaveClass("font-normal", "text-text-secondary");
    expect(search.querySelector("[data-truncate]")).toHaveAttribute("data-truncate", "name");
    const board = within(region).getByRole("link", { name: "Team" });
    expect(board).toHaveAttribute("href", "/dashboard#board=d2");
    // Not pages: the Primary nav keeps its own links only.
    expect(within(nav).queryByRole("link", { name: "Team" })).toBeNull();
    expect(within(nav).getAllByRole("link")).toHaveLength(9);
    // Above Recent, in the same column.
    expect(region.closest("#primary-nav")).not.toBeNull();

    await userEvent.click(board);
    expect(await screen.findByRole("combobox", { name: "Dashboard" })).toHaveValue("d2");
  });

  it("opens a pinned saved search on Saved searches", async () => {
    await rail("/alerts", { ...ADMIN, pins: [SEARCH] });
    const region = await screen.findByRole("navigation", { name: "Pinned" });
    await userEvent.click(within(region).getByRole("link", { name: "Failed SSH by source" }));
    expect(
      await screen.findByRole("region", { name: "Run Failed SSH by source" }),
    ).toBeInTheDocument();
    expect(window.location.pathname + window.location.hash).toBe(
      "/investigate/saved#open=failed_by_ip",
    );
  });

  it("opens a saved search from its address, as a new tab does, and says when it is gone", async () => {
    await rail("/investigate/saved#open=failed_by_ip", ADMIN);
    expect(
      await screen.findByRole("region", { name: "Run Failed SSH by source" }),
    ).toBeInTheDocument();
    // Pin and Unpin in the opened search too.
    const runner = screen.getByRole("region", { name: "Run Failed SSH by source" });
    await userEvent.click(within(runner).getByRole("button", { name: "Pin Failed SSH by source" }));
    expect(await screen.findByRole("navigation", { name: "Pinned" })).toBeInTheDocument();
    await userEvent.click(
      await within(runner).findByRole("button", { name: "Unpin Failed SSH by source" }),
    );
    await vi.waitFor(() => expect(screen.queryByRole("navigation", { name: "Pinned" })).toBeNull());
    cleanup();
    await rail("/investigate/saved#open=no_such_search", ADMIN);
    expect(
      await screen.findByText("That saved search is gone or no longer shared with you."),
    ).toBeInTheDocument();
  });

  it("drops a pinned saved search at once when it is deleted", async () => {
    await rail("/investigate/saved", { ...ADMIN, pins: [SEARCH, BOARD] });
    await screen.findByRole("navigation", { name: "Pinned" });
    await userEvent.click(
      await screen.findByRole("button", { name: "Delete Failed SSH by source" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await vi.waitFor(() => expect(pinned()).toEqual(["Team"]));
  });

  it("follows a pinned dashboard renamed or deleted on the Dashboard", async () => {
    await rail("/dashboard", {
      ...ADMIN,
      pins: [{ kind: "dashboard", id: "d1", name: "My dashboard" }],
    });
    await screen.findByRole("navigation", { name: "Pinned" });
    await userEvent.click(await screen.findByRole("button", { name: "Edit layout" }));
    const name = await screen.findByRole("textbox", { name: "Dashboard name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Weekly AI review");
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    await vi.waitFor(() => expect(pinned()).toEqual(["Weekly AI review"]));
    await userEvent.click(screen.getByRole("button", { name: "Delete dashboard" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete dashboard" }));
    await vi.waitFor(() => expect(screen.queryByRole("navigation", { name: "Pinned" })).toBeNull());
  });

  it("drops a shared dashboard its owner stopped sharing once the dashboards are read again", async () => {
    await rail("/alerts", { mode: "login", signedIn: true, role: "analyst", pins: [BOARD] });
    await screen.findByRole("navigation", { name: "Pinned" });
    // The owner unshares it; the next read of the dashboards, anywhere, refreshes the pins.
    const { api } = await import("@/lib/api");
    await act(() => client.prefetchQuery({ queryKey: ["dashboards"], queryFn: api.dashboards }));
    await fetch("/api/dashboards/d2", { method: "PATCH", body: JSON.stringify({ shared: false }) });
    await act(() => client.invalidateQueries({ queryKey: ["dashboards"] }));
    await vi.waitFor(() => expect(screen.queryByRole("navigation", { name: "Pinned" })).toBeNull());
  });

  it("switches to a pinned dashboard for good, out of Edit layout, and says when one is gone", async () => {
    await rail("/dashboard", { ...ADMIN, pins: [BOARD] });
    const picker = await screen.findByRole("combobox", { name: "Dashboard" });
    expect(picker).toHaveValue("d1");
    await userEvent.click(screen.getByRole("button", { name: "Edit layout" }));
    expect(await screen.findByRole("region", { name: "Dashboard settings" })).toBeInTheDocument();
    const region = screen.getByRole("navigation", { name: "Pinned" });
    await userEvent.click(within(region).getByRole("link", { name: "Team" }));
    await vi.waitFor(() => expect(picker).toHaveValue("d2"));
    expect(screen.queryByRole("region", { name: "Dashboard settings" })).toBeNull();
    // The rail's Dashboard (no address) keeps the board the pin opened.
    const nav = screen.getByRole("navigation", { name: "Primary" });
    await userEvent.click(within(nav).getByRole("link", { name: "Dashboard" }));
    expect(window.location.hash).toBe("");
    expect(screen.getByRole("combobox", { name: "Dashboard" })).toHaveValue("d2");
    // Picking another clears the address.
    await userEvent.click(within(region).getByRole("link", { name: "Team" }));
    expect(window.location.hash).toBe("#board=d2");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Dashboard" }), "d1");
    expect(window.location.hash).toBe("");
    expect(screen.getByRole("combobox", { name: "Dashboard" })).toHaveValue("d1");

    cleanup();
    await rail("/dashboard#board=gone", ADMIN);
    expect(
      await screen.findByText("That dashboard is gone or no longer shared with you."),
    ).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Dashboard" })).toHaveValue("d1");
  });

  it("pins and unpins a saved search from its row", async () => {
    await rail("/investigate/saved", ADMIN);
    const pin = await screen.findByRole("button", { name: "Pin Failed SSH by source" });
    expect(pin).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(pin);
    expect(await screen.findByRole("navigation", { name: "Pinned" })).toBeInTheDocument();
    expect(pinned()).toEqual(["Failed SSH by source"]);
    const unpin = await screen.findByRole("button", { name: "Unpin Failed SSH by source" });
    expect(unpin).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(unpin);
    await vi.waitFor(() => expect(screen.queryByRole("navigation", { name: "Pinned" })).toBeNull());
  });

  it("pins the dashboard on screen", async () => {
    await rail("/dashboard", ADMIN);
    await userEvent.click(await screen.findByRole("button", { name: "Pin My dashboard" }));
    expect(await screen.findByRole("navigation", { name: "Pinned" })).toBeInTheDocument();
    expect(pinned()).toEqual(["My dashboard"]);
  });

  it("waits for an unpin at five pins", async () => {
    const five = ["d1", "d2", "d3", "d4", "d5"].map((id) => ({
      kind: "dashboard" as const,
      id,
      name: id,
    }));
    await rail("/investigate/saved", { ...ADMIN, pins: five });
    await threeMoreBoards();
    const pin = await screen.findByRole("button", { name: "Pin Failed SSH by source" });
    await vi.waitFor(() => expect(pin).toBeDisabled());
    expect(pin).toHaveAttribute("title", "At most 5 pins. Unpin one first.");
  });

  it("lets Recent give way first on a short window, more with more pins", async () => {
    window.localStorage.setItem(
      "app.recent.u1",
      JSON.stringify([{ kind: "host", value: "ws-0042" }]),
    );
    const five = ["d1", "d2", "d3", "d4", "d5"].map((id) => ({
      kind: "dashboard" as const,
      id,
      name: id,
    }));
    await rail("/alerts", { ...ADMIN, pins: five });
    await threeMoreBoards();
    const region = await screen.findByRole("navigation", { name: "Pinned" });
    const recent = await screen.findByRole("navigation", { name: "Recent" });
    expect(recent).toHaveClass("[@media(max-height:809px)]:hidden");
    expect(region).toHaveClass("[@media(max-height:619px)]:hidden");
    const rows = within(region).getAllByRole("listitem");
    expect(rows[3]).toHaveClass("[@media(max-height:699px)]:hidden");
    expect(rows[2]).not.toHaveClass("[@media(max-height:699px)]:hidden");
  });
});
