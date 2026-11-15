import { QueryClient } from "@tanstack/react-query";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

/** D258: the rail's Recent (the last five entities opened, in this browser, per user) and
 * its counts on AI usage and Health. */
let client: QueryClient;
let spy: ReturnType<typeof mockApi>;

async function rail(path: string, auth: MockAuth) {
  window.history.replaceState(null, "", path);
  spy = mockApi("Codename", auth);
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
  return screen.findByRole("navigation", { name: "Primary" });
}

const stored = (user = "u1") =>
  (
    JSON.parse(window.localStorage.getItem(`app.recent.${user}`) ?? "[]") as { value: string }[]
  ).map((k) => k.value);
const asked = (end: string) => spy.mock.calls.filter(([u]) => String(u).endsWith(end)).length;

const ADMIN: MockAuth = { mode: "login", signedIn: true, role: "admin" };

/** Opens an entity's page the way every link does, through its address. */
async function open(section: string) {
  const { navigate } = await import("@/lib/route");
  act(() => navigate("investigate", section));
  await screen.findByRole("navigation", { name: "Recent" });
}

const recent = () =>
  within(screen.getByRole("navigation", { name: "Recent" }))
    .getAllByRole("link")
    .map((a) => a.textContent);

afterEach(() => window.history.replaceState(null, "", "/"));

describe("Rail Recent (D258)", () => {
  it("is hidden until an entity is opened", async () => {
    await rail("/alerts", ADMIN);
    await screen.findByRole("heading", { level: 1, name: "Alerts" });
    expect(screen.queryByRole("navigation", { name: "Recent" })).toBeNull();
  });

  it("keeps people, hosts, and addresses opened, newest first, once each, at most five", async () => {
    const nav = await rail("/investigate/people#user=alice", ADMIN);
    await screen.findByRole("navigation", { name: "Recent" });
    await open("host=ws-0042");
    await open("ip=203.0.113.9");
    expect(recent()).toEqual(["203.0.113.9", "ws-0042", "alice"]);

    // Opening one again moves it to the top.
    await open("user=alice");
    expect(recent()).toEqual(["alice", "203.0.113.9", "ws-0042"]);

    // Each row opens its page, with an icon by kind and the full value as its tooltip.
    const row = within(screen.getByRole("navigation", { name: "Recent" })).getByRole("link", {
      name: "203.0.113.9",
    });
    expect(row).toHaveAttribute("href", "/investigate/people#ip=203.0.113.9");
    expect(row).toHaveAttribute("title", "Address: 203.0.113.9");
    expect(row).toHaveClass("font-normal", "text-text-secondary");
    expect(row.querySelector("svg")).toHaveAttribute("width", "14");

    // Long values are cut by the shared Truncate (D257): an email keeps its local part,
    // a host is cut in the middle; the link carries the full value as its name.
    await open("user=frank.longname@example.com");
    await open("host=workstation-finance-0042");
    const nav2 = screen.getByRole("navigation", { name: "Recent" });
    const email = within(nav2).getByRole("link", { name: "frank.longname@example.com" });
    expect(email.querySelector("[data-truncate]")).toHaveAttribute("data-truncate", "email");
    expect(email.querySelector('[data-part="head"]')).toHaveTextContent("frank.longname");
    const host = within(nav2).getByRole("link", { name: "workstation-finance-0042" });
    expect(host.querySelector("[data-truncate]")).toHaveAttribute("data-truncate", "name");
    expect(host.querySelector('[data-part="tail"]')).toHaveTextContent("nce-0042");
    expect(host.querySelector("[data-truncate]")).not.toHaveAttribute("tabindex");

    for (const v of ["bob", "carol", "dave"]) await open(`user=${v}`);
    expect(recent()).toEqual([
      "dave",
      "carol",
      "bob",
      "workstation-finance-0042",
      "frank.longname@example.com",
    ]);

    // Its own region: the Primary nav still holds the pages only.
    expect(within(nav).queryByRole("link", { name: "dave" })).toBeNull();
    expect(within(nav).getAllByRole("link")).toHaveLength(9);
  });

  it("survives a reload, and is kept per signed-in user", async () => {
    await rail("/investigate/people#host=ws-0042", ADMIN);
    await screen.findByRole("navigation", { name: "Recent" });
    cleanup();

    await rail("/alerts", ADMIN);
    expect(await screen.findByRole("navigation", { name: "Recent" })).toBeInTheDocument();
    expect(recent()).toEqual(["ws-0042"]);
    cleanup();

    await rail("/alerts", { ...ADMIN, userId: "u7" });
    await screen.findByRole("heading", { level: 1, name: "Alerts" });
    expect(screen.queryByRole("navigation", { name: "Recent" })).toBeNull();
  });

  it("holds no people for a viewer without View people in AI usage (D242)", async () => {
    // Kept while the viewer still had the permission.
    window.localStorage.setItem(
      "app.recent.u1",
      JSON.stringify([
        { kind: "user", value: "alice" },
        { kind: "ip", value: "198.51.100.7" },
      ]),
    );
    await rail("/investigate/people#user=bob", { mode: "login", signedIn: true, role: "analyst" });
    await open("host=ws-0042");
    expect(recent()).toEqual(["ws-0042", "198.51.100.7"]);
    // Neither the person opened now nor the one kept before stays in the browser.
    expect(stored()).toEqual(["ws-0042", "198.51.100.7"]);
  });

  it("removes people kept before as soon as the viewer is known to lack the permission", async () => {
    window.localStorage.setItem(
      "app.recent.u1",
      JSON.stringify([
        { kind: "user", value: "alice" },
        { kind: "host", value: "ws-0042" },
      ]),
    );
    await rail("/alerts", { mode: "login", signedIn: true, role: "analyst" });
    await screen.findByRole("navigation", { name: "Recent" });
    expect(recent()).toEqual(["ws-0042"]);
    expect(stored()).toEqual(["ws-0042"]);
  });

  it("is cleared at sign-out, so the next person at the browser cannot read it", async () => {
    await rail("/investigate/people#user=alice", ADMIN);
    await screen.findByRole("navigation", { name: "Recent" });
    expect(stored()).toEqual(["alice"]);
    await userEvent.click(await screen.findByRole("button", { name: /^jordan/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(window.localStorage.getItem("app.recent.u1")).toBeNull();
  });

  it("is cleared when the session is found ended", async () => {
    window.localStorage.setItem(
      "app.recent.u1",
      JSON.stringify([{ kind: "user", value: "alice" }]),
    );
    window.history.replaceState(null, "", "/alerts");
    mockApi("Codename", { mode: "login", signedIn: false });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    render(<App initialTheme="dark" queryClient={new QueryClient()} />);
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(window.localStorage.getItem("app.recent.u1")).toBeNull();
  });

  it("renders without storage", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const nav = await rail("/investigate/people#user=alice", ADMIN);
    expect(within(nav).getAllByRole("link")).toHaveLength(9);
    expect(screen.queryByRole("navigation", { name: "Recent" })).toBeNull();
  });
});

describe("Rail counts (D258)", () => {
  it("puts the AI items to review beside AI usage, outlined and neutral, opening the Inventory", async () => {
    const nav = await rail("/alerts", { ...ADMIN, aiToReview: 3 });
    const ai = within(nav).getByRole("link", { name: /^AI usage/ });
    const count = await within(ai).findByLabelText("3 to review", {}, { timeout: 5000 });
    expect(count).toHaveClass("border", "border-border-strong", "text-text-secondary");
    expect(count).not.toHaveClass("bg-sev-h-solid");
    expect(ai).toHaveAttribute("href", "/ai/inventory");
  });

  it("shows no AI usage count at zero, and AI usage opens on its first tab", async () => {
    const nav = await rail("/alerts", ADMIN);
    await screen.findByRole("heading", { level: 1, name: "Alerts" });
    await new Promise((r) => setTimeout(r, 3000)); // past the rail's first read
    const ai = within(nav).getByRole("link", { name: /^AI usage/ });
    expect(ai.querySelector("[data-ai-count]")).toBeNull();
    expect(ai).toHaveAttribute("href", "/ai");
  });

  it("drops at once when an AI Watch alert is reviewed on Alerts, and AI usage opens on its first tab at zero", async () => {
    const nav = await rail("/alerts", { ...ADMIN, aiToReview: 1 });
    const ai = within(nav).getByRole("link", { name: /^AI usage/ });
    await within(ai).findByLabelText("1 to review", {}, { timeout: 5000 });
    expect(ai).toHaveAttribute("href", "/ai/inventory");
    const list = await screen.findByRole("list", { name: "Alert list" });
    await userEvent.click(within(list).getByRole("button", { name: /New AI service: DeepSeek/ }));
    await userEvent.click(screen.getByRole("button", { name: "Not approved" }));
    await vi.waitFor(() => expect(ai.querySelector("[data-ai-count]")).toBeNull());
    expect(ai).toHaveAttribute("href", "/ai");
  });

  it("follows the Inventory a page already loaded, without a request of its own", async () => {
    const nav = await rail("/alerts", { ...ADMIN, aiToReview: 2 });
    const { api } = await import("@/lib/api");
    const loaded = await api.aiInventory(30);
    // The page's Inventory, with one item nobody has reviewed yet.
    const inventory = {
      ...loaded,
      items: loaded.items.map((i, k) =>
        k === 0 ? { ...i, status: "unreviewed" as const, excluded: null } : i,
      ),
    };
    const { toReview } = await import("@/features/ai/review");
    const n = toReview(inventory.items);
    expect(n).toBeGreaterThan(0);
    expect(n).not.toBe(2); // tells the page's answer apart from the count's
    act(() => client.setQueryData(["ai-usage", "inventory"], inventory));
    await new Promise((r) => setTimeout(r, 3000)); // past the rail's first read
    expect(asked("/api/ai/inventory/count")).toBe(0);
    const ai = within(nav).getByRole("link", { name: /^AI usage/ });
    expect(within(ai).getByLabelText(`${n} to review`)).toBeInTheDocument();

    // A review invalidates that Inventory: the rail no longer trusts it and asks the count.
    await act(() => client.invalidateQueries({ queryKey: ["ai-usage"] }));
    await within(ai).findByLabelText("2 to review");
    expect(asked("/api/ai/inventory/count")).toBe(1);
  });
});
