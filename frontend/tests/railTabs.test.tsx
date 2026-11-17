import { QueryClient } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AREAS, RAIL_DESCRIPTIONS, visibleTabs } from "@/lib/nav";
import { fitTabs, railFit } from "@/lib/railFit";
import { pathFor } from "@/lib/route";
import { mockApi, type MockAuth } from "./mockApi";

/** D268: the current page's tabs in the rail, a description per entry, the empty Pinned. */
async function rail(path: string, auth: MockAuth) {
  window.history.replaceState(null, "", path);
  mockApi("Codename", auth);
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
  return screen.findByRole("navigation", { name: "Primary" });
}

const ADMIN: MockAuth = { mode: "login", signedIn: true, role: "admin" };
const AUDITOR: MockAuth = { mode: "login", signedIn: true, role: "auditor" };
const labels = (el: HTMLElement) =>
  within(el)
    .getAllByRole("link")
    .map((a) => a.textContent);
/** Pages with a tab bar for an administrator: every one must expand in the rail. */
const TABBED = AREAS.filter((a) => visibleTabs(a, true).length > 1);

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
});

describe("Rail: the current page's tabs (D268)", () => {
  it("covers every page with tabs", () => {
    expect(TABBED.map((a) => a.id)).toEqual(["alerts", "logs", "ai", "agents", "health"]);
  });

  it.each(TABBED.map((a) => [a.label, a] as const))(
    "lists %s's tabs as its tab bar does, the open one current",
    async (_, area) => {
      const second = visibleTabs(area, true)[1]!;
      const nav = await rail(pathFor(second.page, second.tab), ADMIN);
      const bar = await screen.findByRole("navigation", { name: `${area.label} tabs` });
      const list = within(nav).getByRole("list", { name: `${area.label} tabs` });
      // One list, two places: the rail's rows equal the header's tabs, in order.
      expect(labels(list)).toEqual(
        within(bar)
          .getAllByRole("link")
          .map((a) => a.firstChild?.textContent),
      );
      expect(within(list).getByRole("link", { name: second.label })).toHaveAttribute(
        "aria-current",
        "page",
      );
      expect(
        within(list)
          .getAllByRole("link")
          .filter((a) => a.getAttribute("aria-current")),
      ).toHaveLength(1);
      expect(nav.querySelector(`[data-rail-entry="${area.id}"]`)).toHaveAttribute(
        "aria-current",
        "true",
      );
      // Only the current page expands; hidden in the icon-only rail.
      expect(nav.querySelectorAll("ul ul")).toHaveLength(1);
      expect(list).toHaveClass("md:max-[1099px]:hidden");
    },
  );

  it("opens a tab from the rail", async () => {
    const nav = await rail("/ai/services", ADMIN);
    const list = within(nav).getByRole("list", { name: "AI usage tabs" });
    await userEvent.click(within(list).getByRole("link", { name: "People" }));
    expect(window.location.pathname).toBe("/ai/people");
    expect(within(list).getByRole("link", { name: "People" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("does not expand a page without tabs, Settings, or tabs a role cannot use", async () => {
    let nav = await rail("/dashboard", ADMIN);
    await screen.findByRole("heading", { level: 1, name: "Dashboard" });
    expect(nav.querySelector("ul ul")).toBeNull();
    expect(nav.querySelector('[data-rail-entry="dashboard"]')).toHaveAttribute(
      "aria-current",
      "page",
    );
    cleanup();
    nav = await rail("/sources", ADMIN);
    await screen.findByRole("navigation", { name: "Settings" });
    expect(nav.querySelector("ul ul")).toBeNull();
    cleanup();
    // An Auditor without Auditor SQL has no Search tab: Logs has one tab, so no list.
    nav = await rail("/investigate/saved", AUDITOR);
    await screen.findByRole("heading", { level: 1 });
    expect(within(nav).queryByRole("list", { name: "Logs tabs" })).toBeNull();
    expect(within(nav).queryByRole("link", { name: "Search" })).toBeNull();
  });
});

describe("Rail: one description per entry (D268)", () => {
  it("gives every entry a plain one-line description, never its name", async () => {
    const nav = await rail("/ai/people", ADMIN);
    const entries = [...nav.querySelectorAll<HTMLElement>("[data-rail-entry]")];
    expect(entries.map((e) => e.dataset.railEntry)).toEqual([
      "dashboard",
      "alerts",
      "logs",
      "ask",
      "people",
      "ai",
      "agents",
      "health",
      "settings",
    ]);
    for (const e of entries) {
      const key = e.dataset.railEntry!;
      const text = RAIL_DESCRIPTIONS[key];
      expect(text, key).toBeTruthy();
      expect(text!.length, key).toBeLessThanOrEqual(50);
      expect(text).not.toMatch(/\u2014|grimoire|seance|séance|ossuary|codename/i);
      expect(e).toHaveAccessibleDescription(text!);
      expect(e).not.toHaveAccessibleName(new RegExp(text!));
      expect(e).not.toHaveAttribute("title");
      // The icon-only rail leads with the label, kept out of the description.
      // Beside the link, never inside it, so it is not part of the link's name.
      expect(e.querySelector('[role="tooltip"]')).toBeNull();
      const tip = e.parentElement!.querySelector('[role="tooltip"]')!;
      expect(tip.textContent).toMatch(new RegExp(`: ${text}$`));
      // Shown only while open: after a short rest of the pointer, or on keyboard focus.
      expect(tip).toHaveClass("hidden", "md:data-[open]:block");
      expect(tip).not.toHaveAttribute("data-open");
    }
    expect(within(nav).getByRole("link", { name: "Logs" })).toHaveAccessibleDescription(
      "Search every event",
    );
  });
});

describe("Rail: the tooltip waits for the pointer, not the keyboard (D268)", () => {
  const tipOf = (link: HTMLElement) =>
    link.parentElement!.querySelector<HTMLElement>('[role="tooltip"]')!;

  it("opens 150 ms after hover, off the rail, and closes at once on leave", async () => {
    const nav = await rail("/ai/people", ADMIN);
    const alerts = nav.querySelector<HTMLElement>('[data-rail-entry="alerts"]')!;
    // 8px off the rail's right edge, not the link's.
    vi.spyOn(nav.closest("#primary-nav")!, "getBoundingClientRect").mockReturnValue({
      right: 208,
    } as DOMRect);
    vi.useFakeTimers();
    try {
      fireEvent.mouseEnter(alerts);
      act(() => vi.advanceTimersByTime(149));
      expect(tipOf(alerts)).not.toHaveAttribute("data-open");
      act(() => vi.advanceTimersByTime(1));
      expect(tipOf(alerts)).toHaveAttribute("data-open");
      expect(tipOf(alerts).style.left).toBe("216px");
      fireEvent.mouseLeave(alerts);
      expect(tipOf(alerts)).not.toHaveAttribute("data-open");
      // Passing over an entry opens nothing.
      fireEvent.mouseEnter(alerts);
      act(() => vi.advanceTimersByTime(100));
      fireEvent.mouseLeave(alerts);
      act(() => vi.advanceTimersByTime(500));
      expect(tipOf(alerts)).not.toHaveAttribute("data-open");
    } finally {
      vi.useRealTimers();
    }
  });

  it("opens at once on keyboard focus and closes on blur", async () => {
    const nav = await rail("/ai/people", ADMIN);
    const dashboard = nav.querySelector<HTMLElement>('[data-rail-entry="dashboard"]')!;
    await userEvent.tab();
    while (document.activeElement !== dashboard) await userEvent.tab();
    expect(tipOf(dashboard)).toHaveAttribute("data-open");
    await userEvent.tab();
    expect(tipOf(dashboard)).not.toHaveAttribute("data-open");
  });
});

describe("Rail: Health's one tooltip, and closing on a click (D268)", () => {
  const tipOf = (link: HTMLElement) =>
    link.parentElement!.querySelector<HTMLElement>('[role="tooltip"]')!;

  it("leads Health's tooltip with its state when something is wrong, at every width", async () => {
    let nav = await rail("/alerts", {
      ...ADMIN,
      healthCount: { total: 8, not_healthy: 3, unhealthy: 0 },
    });
    let health = await within(nav).findByRole(
      "link",
      { name: "Health: 3 sources need attention" },
      { timeout: 5000 },
    );
    const tip = tipOf(health);
    expect(tip).toHaveTextContent(
      "Health: 3 sources need attention. Whether every source and collector is sending",
    );
    // The state shows in the icon-only rail too, where the label is not repeated.
    const lead = tip.firstElementChild!;
    expect(lead).toHaveTextContent("Health: 3 sources need attention.");
    expect(lead).not.toHaveClass("min-[1100px]:hidden");
    expect(tip.textContent).not.toMatch(/^Health: Health/);
    expect(health).toHaveAccessibleDescription("Whether every source and collector is sending");
    expect(health.querySelector("[title]")).toBeNull();
    cleanup();
    // Healthy: the description alone, with the label first only in the icon-only rail.
    nav = await rail("/alerts", ADMIN);
    health = within(nav).getByRole("link", { name: "Health" });
    expect(tipOf(health)).toHaveTextContent(
      /^Health: Whether every source and collector is sending$/,
    );
    expect(tipOf(health).firstElementChild).toHaveClass("min-[1100px]:hidden");
  });

  it("closes an open tooltip on a click and when the page changes", async () => {
    const nav = await rail("/alerts", ADMIN);
    const logs = nav.querySelector<HTMLElement>('[data-rail-entry="logs"]')!;
    vi.useFakeTimers();
    try {
      fireEvent.mouseEnter(logs);
      act(() => vi.advanceTimersByTime(150));
      expect(tipOf(logs)).toHaveAttribute("data-open");
      fireEvent.click(logs);
      expect(tipOf(logs)).not.toHaveAttribute("data-open");
      // A timer still pending does not open it after the click.
      fireEvent.mouseEnter(logs);
      fireEvent.click(logs);
      act(() => vi.advanceTimersByTime(500));
      expect(tipOf(logs)).not.toHaveAttribute("data-open");
      // A new page (Back, a tab, a link elsewhere) closes it too.
      fireEvent.mouseEnter(logs);
      act(() => vi.advanceTimersByTime(150));
      const { navigate } = await import("@/lib/route");
      act(() => navigate("dashboard"));
      expect(tipOf(logs)).not.toHaveAttribute("data-open");
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("Rail: Pinned with no pins (D268)", () => {
  it("says where pins go, as a muted line that is not a link", async () => {
    await rail("/alerts", ADMIN);
    const line = await screen.findByText("Pin a dashboard or saved search here");
    expect(line.tagName).toBe("P");
    expect(line).toHaveClass("text-text-muted");
    expect(line.closest("a")).toBeNull();
    expect(line.closest("[data-pinned-empty]")).toHaveClass("md:max-[1099px]:hidden");
    expect(screen.queryByRole("navigation", { name: "Pinned" })).toBeNull();
  });

  it("gives way on a short window", async () => {
    const tall = window.innerHeight;
    try {
      window.innerHeight = 600;
      await rail("/alerts", ADMIN);
      await screen.findByRole("heading", { level: 1, name: "Alerts" });
      expect(screen.queryByText("Pin a dashboard or saved search here")).toBeNull();
      act(() => {
        window.innerHeight = 900;
        window.dispatchEvent(new Event("resize"));
      });
      expect(await screen.findByText("Pin a dashboard or saved search here")).toBeVisible();
    } finally {
      window.innerHeight = tall;
    }
  });
});

describe("Rail: never scrolls with an expanded page (D268)", () => {
  // The rail's heights at Comfortable (DESIGN.md 5): page rows 32px, tab rows 28px, 1px
  // between rows, group labels 20px, 12px under a group, 24px of padding, a 48px top bar.
  const block = (rows: number, row = 32) => (rows ? 20 + rows * row + (rows - 1) + 12 : 0);
  const fixed = 24 + block(2) + block(3) + block(2) + 1 + 8 + 2 * 32 + 1;
  const tabs = (n: number) => (n ? 1 + n * 28 + (n - 1) : 0);

  // From 470px tall, where the pages alone fit; the tab rows give way last.
  it("fits the tab rows, Pinned, and Recent in what the window leaves, at every height", () => {
    for (const all of [0, 2, 3, 4])
      for (const pins of [0, 1, 3, 5])
        for (let h = 470; h <= 1000; h += 5) {
          const tabRows = fitTabs(h, all);
          const fit = railFit(h, tabRows, pins);
          // The empty Pinned line wraps to two lines of 18px with 6px above and below.
          const pinned = pins ? block(fit.pinned) : fit.pinned ? 20 + 48 + 12 : 0;
          const used = fixed + tabs(tabRows) + pinned + block(fit.recent);
          expect(used, `${h}px, ${all} tabs, ${pins} pins`).toBeLessThanOrEqual(h - 48);
          // The tab rows stay while Recent or Pinned still show.
          if (fit.pinned || fit.recent) expect(tabRows).toBe(all);
        }
  });

  it("hides the tab rows only once the pages and tabs no longer fit", async () => {
    expect(fitTabs(590, 4)).toBe(4);
    expect(fitTabs(589, 4)).toBe(0);
    expect(fitTabs(560, 3)).toBe(3);
    expect(fitTabs(400, 0)).toBe(0);
    const tall = window.innerHeight;
    try {
      window.innerHeight = 560;
      const nav = await rail("/alerts", ADMIN);
      expect(within(nav).queryByRole("list", { name: "Alerts tabs" })).toBeNull();
      // Then Alerts is simply the current page; its own tab bar keeps the tabs.
      expect(nav.querySelector('[data-rail-entry="alerts"]')).toHaveAttribute(
        "aria-current",
        "page",
      );
      expect(await screen.findByRole("navigation", { name: "Alerts tabs" })).toBeInTheDocument();
    } finally {
      window.innerHeight = tall;
    }
  });

  it("keeps Recent's and Pinned's rows at 700 and 620px with AI usage open", () => {
    // AI usage: three tab rows. Recent gives way first, then the empty line or the pins.
    expect(railFit(900, 3, 0)).toEqual({ pinned: 1, recent: 5 });
    expect(railFit(850, 3, 0)).toEqual({ pinned: 1, recent: 3 });
    expect(railFit(720, 3, 0)).toEqual({ pinned: 1, recent: 0 });
    expect(railFit(700, 3, 5)).toEqual({ pinned: 0, recent: 0 });
    expect(railFit(620, 3, 0)).toEqual({ pinned: 0, recent: 0 });
    // With no page tabs the rules are D259's as before.
    expect(railFit(700, 0, 5)).toEqual({ pinned: 5, recent: 0 });
    expect(railFit(620, 0, 5)).toEqual({ pinned: 3, recent: 0 });
  });
});
