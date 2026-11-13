import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

async function renderAt(path: string) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
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
  return spy;
}

const here = () => window.location.pathname + window.location.hash;

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("Old Alerts addresses (ADR-0052 sections 3.3 and 3.4, redesign build row 5)", () => {
  it.each([
    ["/alerts/closed", "/alerts#state=closed"],
    ["/alerts/muted", "/alerts#state=muted"],
    ["/alerts/open", "/alerts"],
    ["/alerts/closed#item=g1", "/alerts#state=closed&item=g1"],
    ["/alerts/open#item=a1", "/alerts#item=a1"],
    ["/alerts/closed/", "/alerts#state=closed"],
    // Before tabs had paths (#274) the tab was a bare word in the fragment.
    ["/alerts#closed", "/alerts#state=closed"],
    ["/alerts#muted", "/alerts#state=muted"],
    ["/alerts#open", "/alerts"],
    // The query string is kept.
    ["/alerts/closed?from=mail", "/alerts?from=mail#state=closed"],
    ["/alerts/muted?from=mail#item=g1", "/alerts?from=mail#state=muted&item=g1"],
  ])("sends %s to %s, keeping what the fragment held", async (old, now) => {
    const { canonical, pageFromPath } = await import("@/lib/route");
    window.history.replaceState(null, "", old);
    expect(pageFromPath((old.split("#")[0] ?? "").split("?")[0] ?? "")).toBe("alerts");
    expect(canonical()).toBe(now);
  });

  it("leaves the new addresses alone", async () => {
    const { canonical } = await import("@/lib/route");
    for (const path of ["/alerts", "/alerts#state=closed", "/alerts#item=a1", "/alerts/rules"]) {
      window.history.replaceState(null, "", path);
      expect(canonical(), path).toBeNull();
    }
  });

  it("redirects with replace: Back does not land on the old address", async () => {
    const before = window.history.length;
    await renderAt("/alerts/closed");
    await waitFor(() => expect(here()).toBe("/alerts#state=closed"));
    expect(window.history.length).toBe(before);
    expect(await stateButton("Closed")).toHaveAttribute("aria-pressed", "true");
  });
});

/** One choice of the State filter, a segmented control in the filter bar. */
async function stateButton(name: string): Promise<HTMLElement> {
  const group = await screen.findByRole("group", { name: "State" });
  return within(group).getByRole("button", { name: new RegExp(`^${name}`) });
}

describe("Alerts tabs and the State filter", () => {
  it("has three tabs, Queue, Rules, Schedules, with the open count on Queue", async () => {
    await renderAt("/alerts");
    const tabs = await screen.findByRole("navigation", { name: "Alerts tabs" });
    const names = within(tabs)
      .getAllByRole("link")
      .map((a) => a.textContent?.replace(/\d+$/, "").trim());
    expect(names).toEqual(["Queue", "Rules", "Schedules"]);
    const queue = within(tabs).getByRole("link", { name: /^Queue/ });
    expect(queue).toHaveAttribute("aria-current", "page");
    await waitFor(() => expect(queue).toHaveTextContent(/Queue\s*2/));
  });

  it("filters by State from the address, Open by default, and writes the choice back", async () => {
    await renderAt("/alerts");
    // A segmented control: Open with its count, pressed by default. Muted carries its count
    // when there are mutes, and none when there are none. No Reset on the default.
    const open = await stateButton("Open");
    await waitFor(() => expect(open).toHaveTextContent(/^Open\s*2$/));
    expect(open).toHaveAttribute("aria-pressed", "true");
    expect(await stateButton("Muted")).toHaveTextContent(/^Muted(\s*\d+)?$/);
    expect(screen.queryByRole("button", { name: "Reset" })).toBeNull();
    const list = await screen.findByRole("list", { name: "Alert list" });
    expect(within(list).getByRole("button", { name: /Failed logons/ })).toBeVisible();

    await userEvent.click(await stateButton("Closed"));
    expect(here()).toBe("/alerts#state=closed");
    expect(screen.getByRole("button", { name: "Reset" })).toBeVisible();
    await waitFor(() => expect(screen.queryByRole("button", { name: /Failed logons/ })).toBeNull());

    // Muted shows the mutes, and the filter is still there to go back.
    await userEvent.click(await stateButton("Muted"));
    expect(here()).toBe("/alerts#state=muted");
    await userEvent.click(await stateButton("Open"));
    expect(here()).toBe("/alerts");
  });

  it("never filters open alerts by time: there is no Time control on Open", async () => {
    // A time in the address changes nothing on Open, however old the alerts are.
    await renderAt("/alerts#time=1h");
    const list = await screen.findByRole("list", { name: "Alert list" });
    expect(within(list).getByRole("button", { name: /Failed logons/ })).toBeVisible();
    expect(within(list).getByRole("button", { name: /DeepSeek/ })).toBeVisible();
    expect(document.querySelector("[data-filter-count]")).toHaveTextContent(/^2 alerts$/);
    expect(screen.queryByRole("group", { name: "Time" })).toBeNull();
  });

  it("filters Closed by when an alert was closed, 7 days unless chosen, with Custom for the rest", async () => {
    // The closed alert of the fixtures was closed on 2026-10-22, long before the last 7 days.
    await renderAt("/alerts#state=closed");
    const time = await screen.findByRole("group", { name: "Time" });
    expect(within(time).getByRole("button", { name: "7 days" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      within(time)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["1 hour", "24 hours", "7 days", "30 days", "Custom"]);
    // (The fixture has alerts this viewer cannot read, so no sentence says "none".)
    await waitFor(() => expect(screen.queryByRole("list", { name: "Alert list" })).toBeNull());
    expect(screen.queryByText(/^No alerts closed/)).toBeNull();
    // Custom opens on the window that was showing: its start filled in, nothing new read.
    await userEvent.click(within(time).getByRole("button", { name: "Custom" }));
    const opened = new URLSearchParams(window.location.hash.slice(1));
    expect(opened.get("time")).toBe("custom");
    const startedAt = Date.parse(String(opened.get("from")));
    expect(Date.now() - startedAt).toBeGreaterThan(6.9 * 86_400_000);
    expect(Date.now() - startedAt).toBeLessThan(7.1 * 86_400_000);
    expect(opened.get("to")).toBeNull();
    expect(screen.queryByRole("list", { name: "Alert list" })).toBeNull();
    // With no dates it is everything kept; a start and an end narrow it.
    const from = screen.getByLabelText("From");
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(from, { target: { value: "" } });
    expect(here()).toBe("/alerts#state=closed&time=custom");
    const list = await screen.findByRole("list", { name: "Alert list" });
    expect(within(list).getAllByRole("button").length).toBeGreaterThan(0);
    fireEvent.change(from, { target: { value: "2026-10-23T00:00" } });
    // The address carries the UTC time: the same moment in any time zone.
    expect(here()).toBe(
      `/alerts#state=closed&time=custom&from=${encodeURIComponent(new Date("2026-10-23T00:00").toISOString())}`,
    );
    // (The fixture has alerts this viewer cannot read, so no sentence says "none".)
    await waitFor(() => expect(screen.queryByRole("list", { name: "Alert list" })).toBeNull());
    expect(screen.queryByText(/^No alerts closed/)).toBeNull();
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-21T00:00" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-10-23T00:00" } });
    expect(
      within(await screen.findByRole("list", { name: "Alert list" })).getAllByRole("button").length,
    ).toBeGreaterThan(0);
    // The start says its UTC time on hover.
    expect(screen.getByLabelText("From")).toHaveAttribute("title", expect.stringMatching(/ UTC$/));
  });

  it("still opens a closed alert from #item=<id>, whatever the State filter says", async () => {
    await renderAt("/alerts#item=g1");
    const pane = await screen.findByRole("region", { name: "This alert" });
    expect(await within(pane).findByText("Firewall reboot")).toBeVisible();
    expect(await stateButton("Open")).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps the State filter when another alert is picked from a linked one", async () => {
    await renderAt("/alerts#state=closed&time=custom&item=g1");
    const pane = await screen.findByRole("region", { name: "This alert" });
    expect(await within(pane).findByText("Firewall reboot")).toBeVisible();
    const list = await screen.findByRole("list", { name: "Alert list" });
    await userEvent.click(within(list).getAllByRole("button")[0] as HTMLElement);
    expect(here()).toBe("/alerts#state=closed&time=custom");
  });

  it("shows the alert a link names beside a window it was not closed in", async () => {
    // Closed on 2026-10-22: not in the last 7 days, and still opened by its link.
    await renderAt("/alerts#state=closed&item=g1");
    const pane = await screen.findByRole("region", { name: "This alert" });
    expect(await within(pane).findByText("Firewall reboot")).toBeVisible();
  });

  it("shows Reset only where a filter differs from the default", async () => {
    // A time left in the address means nothing on Open: no Reset there.
    await renderAt("/alerts#time=30d");
    await screen.findByRole("list", { name: "Alert list" });
    expect(screen.queryByRole("button", { name: "Reset" })).toBeNull();
    // Leaving Custom takes its dates out of the address.
    window.history.replaceState(null, "", "/alerts#state=closed&time=custom&from=2026-10-01T00:00");
    window.dispatchEvent(new PopStateEvent("popstate"));
    const time = await screen.findByRole("group", { name: "Time" });
    await userEvent.click(within(time).getByRole("button", { name: "7 days" }));
    expect(here()).toBe("/alerts#state=closed");
  });

  it("keeps every filter in the address, and has no Time control until its default is set", async () => {
    await renderAt("/alerts#sev=high&q=deepseek");
    const list = await screen.findByRole("list", { name: "Alert list" });
    expect(screen.getByRole("combobox", { name: "Severity" })).toHaveValue("high");
    expect(screen.getByRole("textbox", { name: "Person, device, or source" })).toHaveValue(
      "deepseek",
    );
    expect(within(list).queryByRole("button", { name: /Failed logons/ })).toBeNull();
    expect(screen.queryByRole("group", { name: "Time" })).toBeNull();
  });

  it("drops the linked alert when the State changes: a new State is a new list", async () => {
    await renderAt("/alerts#item=g1");
    await userEvent.click(await stateButton("Closed"));
    expect(here()).toBe("/alerts#state=closed");
    await userEvent.click(await stateButton("Open"));
    expect(here()).toBe("/alerts");
  });

  it("writes the text box to the address a moment after typing stops, not on every key", async () => {
    await renderAt("/alerts");
    const box = await screen.findByRole("textbox", { name: "Person, device, or source" });
    const replaced = vi.spyOn(window.history, "replaceState");
    await userEvent.type(box, "deepseek");
    expect(screen.getByRole("button", { name: "Reset" })).toBeVisible();
    await waitFor(() => expect(here()).toBe("/alerts#q=deepseek"));
    expect(replaced.mock.calls.length).toBeLessThan(8);
    await userEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(here()).toBe("/alerts");
    expect(box).toHaveValue("");
  });

  it.each(["sev=loud", "cat=constructor", "state=gone"])(
    "filters nothing and shows no Reset for an unknown value (#%s)",
    async (fragment) => {
      await renderAt(`/alerts#${fragment}`);
      const list = await screen.findByRole("list", { name: "Alert list" });
      expect(within(list).getByRole("button", { name: /Failed logons/ })).toBeVisible();
      expect(document.querySelector("[data-filter-count]")).toHaveTextContent(/^2 alerts$/);
      expect(screen.queryByRole("button", { name: "Reset" })).toBeNull();
    },
  );

  it("offers Reset filters when the filters hide every alert", async () => {
    await renderAt("/alerts#q=nothing-like-this");
    const list = await screen.findByRole("list", { name: "Alert list" });
    expect(within(list).getByText("No alerts match these filters.")).toBeVisible();
    await userEvent.click(within(list).getByRole("button", { name: "Reset filters" }));
    expect(here()).toBe("/alerts");
    expect(await within(list).findByRole("button", { name: /Failed logons/ })).toBeVisible();
  });

  it("filters nothing for an unknown value in the address", async () => {
    await renderAt("/alerts#sev=loud");
    expect(await screen.findByRole("combobox", { name: "Severity" })).toHaveValue("");
    const list = await screen.findByRole("list", { name: "Alert list" });
    expect(within(list).getByRole("button", { name: /Failed logons/ })).toBeVisible();
  });

  it("is still found in Ctrl+K by Closed and Muted, which open the Queue with that state", async () => {
    await renderAt("/health");
    await screen.findByRole("heading", { level: 1, name: "Health" });
    for (const [typed, label, address] of [
      ["closed alerts", "Alerts › Closed", "/alerts#state=closed"],
      ["muted", "Alerts › Muted", "/alerts#state=muted"],
    ] as const) {
      await userEvent.keyboard("{Control>}k{/Control}");
      const dialog = await screen.findByRole("dialog");
      await userEvent.type(within(dialog).getByRole("combobox"), typed);
      await userEvent.click(
        await within(dialog).findByRole("option", { name: new RegExp(`^${label}`) }),
      );
      await waitFor(() => expect(here()).toBe(address));
    }
  });
});
