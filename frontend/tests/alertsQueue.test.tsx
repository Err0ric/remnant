import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AREAS } from "@/lib/nav";
import { mockApi, type MockAuth } from "./mockApi";
import { choose } from "./choose";

async function renderAt(
  path: string,
  auth: MockAuth = { mode: "login", signedIn: true, role: "admin" },
) {
  window.history.replaceState(null, "", path);
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

async function listRow(name: RegExp) {
  const list = await screen.findByRole("list", { name: "Alert list" });
  return within(list).getByRole("button", { name });
}

afterEach(() => vi.restoreAllMocks());

const here = () => window.location.pathname + window.location.hash;

describe("Alerts (ADR-0037, ADR-0043)", () => {
  it("is second in the nav, in the morning's order, with the open count", async () => {
    expect(AREAS.map((a) => a.label).slice(0, 2)).toEqual(["Dashboard", "Alerts"]);
    await renderAt("/alerts");
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    expect(await within(nav).findByLabelText("2 open")).toBeInTheDocument();
  });

  it("has no summary strip, filters the list, and opens one in the pane beside it", async () => {
    await renderAt("/alerts");
    const list = await screen.findByRole("list", { name: "Alert list" });
    // No summary strip (DESIGN.md 6.2e). Alerts in sources the viewer cannot read: one note
    // at the foot of the list, never a count (owner, 2026-11-12).
    expect(screen.queryByRole("region", { name: "Open alerts summary" })).toBeNull();
    expect(screen.queryByText("New today")).toBeNull();
    const note = within(list).getByRole("note");
    expect(note).toHaveTextContent(
      "Some alerts are in sources you can't read. Ask an admin for access.",
    );
    expect(note).not.toHaveTextContent(/\d/);
    expect(list.lastElementChild).toContainElement(note);
    // High first, then by time: DeepSeek opens in the pane on load.
    const pane = screen.getByRole("region", { name: "This alert" });
    expect(within(pane).getByRole("heading", { name: "New AI service: DeepSeek" })).toBeVisible();
    await choose(screen.getByRole("combobox", { name: "Category" }), "Detections");
    expect(within(list).queryByRole("button", { name: /DeepSeek/ })).toBeNull();
    // The count is of alerts this person can read: two, though the source they cannot read
    // has more (the note above), and it says how many of them the filters leave.
    const count = document.querySelector("[data-filter-count]");
    expect(count).toHaveTextContent(/^1 of 2 alerts$/);
    expect(here()).toBe("/alerts#cat=detection");
    // Reset is there only while a filter is off its default, and clears them all.
    await userEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(here()).toBe("/alerts");
    expect(screen.queryByRole("button", { name: "Reset" })).toBeNull();
    expect(count).toHaveTextContent(/^2 alerts$/);
    await choose(screen.getByRole("combobox", { name: "Category" }), "Detections");
    await choose(screen.getByRole("combobox", { name: "Category" }), "");
    await choose(screen.getByRole("combobox", { name: "Severity" }), "high");
    expect(within(list).queryByRole("button", { name: /Failed logons/ })).toBeNull();
    await choose(screen.getByRole("combobox", { name: "Severity" }), "");
    await userEvent.type(
      screen.getByRole("textbox", { name: "Person, device, or source" }),
      "ws-0042",
    );
    expect(within(list).getAllByRole("button")).toHaveLength(1);
    await userEvent.click(await listRow(/Failed logons/));
    expect(within(pane).getByText("Count 12 is above 5")).toBeVisible();
    expect(within(pane).getByText(/A detection rule matched events/)).toBeVisible();
    expect(within(pane).getByRole("list", { name: "Next steps" })).toHaveTextContent(
      "Read the rows that fired",
    );
    // The page uses the full width: no narrow centered column.
    expect(document.querySelector(".max-w-5xl")).toBeNull();
  });

  it("lets an alert title use two lines, then cut, with the whole title on hover (D257)", async () => {
    await renderAt("/alerts");
    const list = await screen.findByRole("list", { name: "Alert list" });
    const title = (await within(list).findByText("New AI service: DeepSeek")) as HTMLElement;
    expect(title).toHaveAttribute("data-alert-title");
    expect(title).toHaveClass("line-clamp-2");
    expect(title).not.toHaveClass("truncate");
    expect(title.closest("button")).toHaveAttribute("title", "New AI service: DeepSeek");
  });

  it("keeps each comma of the pane's People with the person before it (D257)", async () => {
    const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) => {
      const res = await base(input, init);
      if (!String(input).includes("/api/alerts") || !res.ok) return res;
      const body = await res
        .clone()
        .json()
        .catch(() => null);
      if (!body || !Array.isArray(body.items)) return res;
      for (const i of body.items) if (i.item_id === "w1") i.people = ["ana", "bob", "carol"];
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    window.history.replaceState(null, "", "/alerts#item=w1");
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
    const pane = await screen.findByRole("region", { name: "This alert" });
    const people = (await within(pane).findByText("People")).nextElementSibling as HTMLElement;
    expect([...people.querySelectorAll(".whitespace-nowrap")].map((k) => k.textContent)).toEqual([
      "ana,",
      "bob,",
      "carol",
    ]);
  });

  it("closes with a required note for False positive", async () => {
    const spy = await renderAt("/alerts");
    await userEvent.click(await listRow(/Failed logons/));
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    const form = screen.getByRole("form", { name: "Close Failed logons" });
    await userEvent.click(within(form).getByLabelText("False positive"));
    const submit = within(form).getByRole("button", { name: "Close alert" });
    expect(submit).toBeDisabled();
    await userEvent.type(within(form).getByRole("textbox"), "Backup job");
    await userEvent.click(submit);
    const posted = spy.mock.calls.filter(
      ([u, init]) => String(u).endsWith("/api/alerts/a1/close") && init?.method === "POST",
    );
    expect(JSON.parse(String(posted[0]?.[1]?.body))).toEqual({
      reason: "false_positive",
      note: "Backup job",
    });
  });

  it("closes several with one reason", async () => {
    const spy = await renderAt("/alerts");
    const list = await screen.findByRole("list", { name: "Alert list" });
    for (const box of within(list).getAllByRole("checkbox")) await userEvent.click(box);
    const bulk = screen.getByRole("form", { name: "Close selected alerts" });
    expect(bulk).toHaveTextContent("2 selected");
    await choose(within(bulk).getByRole("combobox"), "expected");
    await userEvent.click(within(bulk).getByRole("button", { name: "Close 2" }));
    await vi.waitFor(() => {
      const call = spy.mock.calls.find(([u]) => String(u).endsWith("/api/alerts/close"));
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        item_ids: ["w1", "a1"],
        reason: "expected",
      });
    });
  });

  it("opens the alert a message links to, closed ones too", async () => {
    await renderAt("/alerts#item=g1");
    const here = await screen.findByRole("region", { name: "This alert" });
    expect(await within(here).findByText("Firewall reboot")).toBeVisible();
    expect(within(here).getByText("Events arriving again after 25 min")).toBeInTheDocument();
    expect(within(here).getByRole("button", { name: "Reopen" })).toBeInTheDocument();
    expect(within(here).getByRole("button", { name: /^Show .*events in Logs$/ })).toBeVisible();
  });

  it("lets an auditor read but not close", async () => {
    await renderAt("/alerts", { mode: "login", signedIn: true, role: "auditor" });
    await userEvent.click(await listRow(/Failed logons/));
    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("shows AI Watch severity and lets an admin approve or mute from the pane", async () => {
    const spy = await renderAt("/alerts");
    const row = await listRow(/New AI service: DeepSeek/);
    expect(within(row).getByText("High")).toBeInTheDocument();
    await userEvent.click(row);
    await userEvent.click(screen.getByRole("button", { name: "Not approved" }));
    await userEvent.click(screen.getByRole("button", { name: "30 days" }));
    await vi.waitFor(() => {
      expect(
        spy.mock.calls.some(
          ([u, init]) =>
            String(u).endsWith("/api/ai/services/deepseek/status") && init?.method === "PUT",
        ),
      ).toBe(true);
      const mute = spy.mock.calls.find(([u]) => String(u).endsWith("/api/alerts/w1/mute"));
      expect(JSON.parse(String(mute?.[1]?.body))).toEqual({ days: 30 });
    });
  });

  it("closing an AI Watch alert can set the review status (owner, 2026-10-29)", async () => {
    const spy = await renderAt("/alerts");
    await userEvent.click(await listRow(/New AI service: DeepSeek/));
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    const form = screen.getByRole("form", { name: "Close New AI service: DeepSeek" });
    const review = within(form).getByRole("group", { name: "Review status of this service" });
    expect(within(review).getByLabelText("Leave unreviewed")).toBeChecked();
    await userEvent.click(within(review).getByLabelText("Not approved"));
    await userEvent.click(within(form).getByLabelText("Resolved"));
    await userEvent.click(within(form).getByRole("button", { name: "Close alert" }));
    await vi.waitFor(() => {
      const call = spy.mock.calls.find(([u]) => String(u).endsWith("/api/alerts/w1/close"));
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        reason: "resolved",
        review_status: "not_approved",
      });
    });
  });

  it("lists AI Watch alerts still not reviewed, closed included", async () => {
    const spy = await renderAt("/alerts#review");
    // One line: what the list is, and who reviews (ADR-0052 section 3.7).
    expect(
      await screen.findByText(
        /^Not reviewed yet\. Closing an alert does not review it: an administrator does\./,
      ),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Back to open alerts" })).toBeVisible();
    expect(await listRow(/New AI service: DeepSeek/)).toBeVisible();
    expect(spy.mock.calls.some(([u]) => String(u).includes("unreviewed=true"))).toBe(true);
    expect(screen.queryByRole("button", { name: /stopped sending/ })).toBeNull();
  });

  it("does not offer Approve or mute to an analyst", async () => {
    await renderAt("/alerts", { mode: "login", signedIn: true, role: "analyst" });
    await userEvent.click(await listRow(/New AI service: DeepSeek/));
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "7 days" })).toBeNull();
  });

  it("names who the alert is about and opens the rows around a fired event", async () => {
    await renderAt("/alerts");
    await userEvent.click(await listRow(/Failed logons/));
    const pane = screen.getByRole("region", { name: "This alert" });
    expect(await within(pane).findByRole("link", { name: "alice" })).toBeVisible();
    // The rows that fired are in the one section that starts closed (until the full alert
    // page exists); opening it shows them.
    const more = pane.querySelector("details[data-more]") as HTMLDetailsElement;
    expect(more.open).toBe(false);
    await userEvent.click(within(more).getByText("Evidence, changes, and history"));
    expect(more.open).toBe(true);
    const rows = await screen.findByRole("table", { name: "Rows that fired" });
    await userEvent.click(within(rows).getByRole("button", { name: "Around" }));
    const box = await screen.findByRole("region", { name: "Around this event" });
    expect(await within(box).findByText("Likely cause")).toBeVisible();
  });

  it("keeps the pane slim: Close is the only filled button, the rest is one closed section", async () => {
    await renderAt("/alerts");
    await userEvent.click(await listRow(/New AI service: DeepSeek/));
    const pane = screen.getByRole("region", { name: "This alert" });
    await within(pane).findByRole("heading", { name: "New AI service: DeepSeek" });
    // The alert's id, in mono, with the whole id on hover.
    expect(within(pane).getByTitle("Alert w1")).toHaveClass("font-mono");
    // One filled button: Close. Mute and Show events are not filled.
    const filled = within(pane)
      .getAllByRole("button")
      .filter((b) => /\bbg-accent(?![\w-])/.test(b.className));
    expect(filled.map((b) => b.textContent)).toEqual(["Close"]);
    expect(pane.querySelectorAll("[data-primary]")).toHaveLength(1);
    // The action row: Close, Mute similar, and the alert's events in Logs.
    const close = within(pane).getByRole("button", { name: "Close" });
    const row = close.parentElement as HTMLElement;
    expect(within(row).getByRole("button", { name: "7 days" })).toBeVisible();
    // An empty place for the Triage card (ADR-0049 Phase 1c), drawn as nothing.
    expect(pane.querySelector('[data-slot="triage"]')).toBeEmptyDOMElement();
    // What moves to the full alert page stays reachable, in one section that starts closed.
    const more = pane.querySelector("details[data-more]") as HTMLDetailsElement;
    expect(more.open).toBe(false);
    expect(pane.querySelectorAll("details")).toHaveLength(1);
    expect(within(more).getByText("Evidence, changes, and history")).toBeVisible();
    expect(within(more).getByRole("heading", { name: "Evidence" })).toBeInTheDocument();
    expect(within(more).getByRole("button", { name: "Approve" })).toBeInTheDocument();
    // Next steps stay in the pane itself, above the actions.
    const steps = within(pane).getByRole("list", { name: "Next steps" });
    expect(more.contains(steps)).toBe(false);
    expect(steps.compareDocumentPosition(close) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(close.compareDocumentPosition(more) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("puts the alert's events in the action row, with no number that is not an event count", async () => {
    await renderAt("/alerts");
    await userEvent.click(await listRow(/Failed logons/));
    const pane = screen.getByRole("region", { name: "This alert" });
    const close = await within(pane).findByRole("button", { name: "Close" });
    // In the same row as Close, and outside the closed section.
    const events = within(close.parentElement as HTMLElement).getByRole("button", {
      name: "Show events in Logs",
    });
    expect(events).toBeVisible();
    expect(events.className).not.toMatch(/\bbg-accent(?![\w-])/);
    expect(pane.querySelector("details[data-more]")?.contains(events)).toBe(false);
    // The alert's count (12 here, rows of a run) is not a number of events: never on the button.
    expect(within(pane).queryByRole("button", { name: /Show \d+ events/ })).toBeNull();
  });

  it("says a good zero in plain words, with when it was checked and no action", async () => {
    window.history.replaceState(null, "", "/alerts");
    const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "analyst" });
    const real = spy.getMockImplementation() as typeof fetch;
    spy.mockImplementation(async (url, init) => {
      if (/\/api\/alerts(\?|$)/.test(String(url)) && (init?.method ?? "GET") === "GET")
        return new Response(
          JSON.stringify({ items: [], open: 0, restricted: false, muted: 0, reasons: {} }),
          { headers: { "Content-Type": "application/json" } },
        );
      return real(url, init);
    });
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
    const zero = await screen.findByText("No open alerts. Checked just now.");
    const box = zero.closest("[data-empty]") as HTMLElement;
    expect(box).toHaveAttribute("data-empty", "good-zero");
    expect(within(box).queryByRole("button")).toBeNull();
  });

  it("keeps the restricted note when nothing is listed", async () => {
    window.history.replaceState(null, "", "/alerts");
    const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "analyst" });
    const real = spy.getMockImplementation() as typeof fetch;
    // Every open alert is in a source this viewer cannot read: no items, only the flag.
    spy.mockImplementation(async (url, init) => {
      if (/\/api\/alerts(\?|$)/.test(String(url)) && (init?.method ?? "GET") === "GET")
        return new Response(
          JSON.stringify({ items: [], open: 0, restricted: true, muted: 0, reasons: {} }),
          { headers: { "Content-Type": "application/json" } },
        );
      return real(url, init);
    });
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
    const note = await screen.findByRole("note");
    // Not "No open alerts": there are some, in sources this person cannot read.
    expect(screen.queryByText(/^No open alerts/)).toBeNull();
    expect(note).toHaveTextContent(
      "Some alerts are in sources you can't read. Ask an admin for access.",
    );
    expect(note).not.toHaveTextContent(/\d/);
    // No permission is never shown as zero: no "0 alerts", no "Open 0", no 0 on the tab.
    expect(document.querySelector("[data-filter-count]")).toBeNull();
    const state = screen.getByRole("group", { name: "State" });
    expect(within(state).getByRole("button", { name: /^Open/ })).toHaveTextContent(/^Open$/);
    const tabs = screen.getByRole("navigation", { name: "Alerts tabs" });
    expect(within(tabs).getByRole("link", { name: /^Queue/ })).toHaveTextContent(/^Queue$/);
  });

  it("starts the closed section closed again for every alert", async () => {
    await renderAt("/alerts");
    await userEvent.click(await listRow(/Failed logons/));
    const pane = screen.getByRole("region", { name: "This alert" });
    const more = () => pane.querySelector("details[data-more]") as HTMLDetailsElement;
    await userEvent.click(within(more()).getByText("Evidence, changes, and history"));
    expect(more().open).toBe(true);
    await userEvent.click(await listRow(/New AI service: DeepSeek/));
    await within(pane).findByRole("heading", { name: "New AI service: DeepSeek" });
    expect(more().open).toBe(false);
  });

  it("keeps one filled button on the page when rows are ticked for a bulk close", async () => {
    await renderAt("/alerts");
    const list = await screen.findByRole("list", { name: "Alert list" });
    await userEvent.click(within(list).getAllByRole("checkbox")[0] as HTMLElement);
    const bulk = await screen.findByRole("button", { name: /^Close 1$/ });
    expect(bulk.className).not.toMatch(/\bbg-accent(?![\w-])/);
    const filled = screen
      .getAllByRole("button")
      .filter((b) => /\bbg-accent(?![\w-])/.test(b.className) && !b.closest("header"));
    expect(filled.map((b) => b.textContent)).toEqual(["Close"]);
  });
});
