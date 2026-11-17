import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

type Reply = (url: string) => Response | Promise<Response> | null;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

/** The app at `path`, with `reply` answering the requests it wants to (null: the fixture). */
async function renderAt(path: string, reply: Reply) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
  const real = spy.getMockImplementation() as typeof fetch;
  spy.mockImplementation(async (url, init) => {
    const mine = (init?.method ?? "GET") === "GET" ? reply(String(url)) : null;
    return mine ?? real(url, init);
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
  return spy;
}

const isMutes = (url: string) => /\/api\/alerts\/mutes(\?|$)/.test(url);
const isList = (url: string) => /\/api\/alerts(\?|$)/.test(url);
const empty = { items: [], open: 0, restricted: false, muted: 0, reasons: {} };

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Alerts: the states of the page (DESIGN.md 6.0, redesign build row 14)", () => {
  it("loads in its final layout: the bar, then a list and a pane of placeholder rows", async () => {
    let release: (r: Response) => void = () => undefined;
    const held = new Promise<Response>((resolve) => (release = resolve));
    await renderAt("/alerts", (url) => (isList(url) ? held : null));
    expect(await screen.findByRole("status", { name: "Loading alerts" })).toBeVisible();
    expect(screen.getByRole("status", { name: "Loading the open alert" })).toBeVisible();
    const bar = screen.getByRole("group", { name: "Filter alerts" });
    expect(within(bar).getByRole("group", { name: "State" })).toBeVisible();
    // The same bar element stays when the alerts arrive: nothing above the list moves.
    await act(async () => release(json(empty)));
    await screen.findByText(/^No open alerts\./);
    expect(screen.getByRole("group", { name: "Filter alerts" })).toBe(bar);
    expect(screen.queryByRole("status", { name: "Loading alerts" })).toBeNull();
  });

  it("keeps the bar when the list fails, with the error in place and Retry", async () => {
    await renderAt("/alerts", (url) =>
      isList(url) ? json({ error: { code: "internal", message: "It broke" } }, 500) : null,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/^Alerts did not load: /);
    expect(screen.getByRole("button", { name: "Retry" })).toBeVisible();
    expect(screen.getByRole("group", { name: "Filter alerts" })).toBeVisible();
  });

  it("keeps the time since the last check true on a page left open", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await renderAt("/alerts", (url) => (isList(url) ? json(empty) : null));
    expect(await screen.findByText("No open alerts. Checked just now.")).toBeVisible();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10 * 60_000);
    });
    await waitFor(() =>
      expect(screen.getByText(/^No open alerts\. Checked \d+ min ago\.$/)).toBeVisible(),
    );
  });

  it("says Pick an alert beside a list the filters emptied", async () => {
    await renderAt("/alerts#q=nothing-like-this", () => null);
    const pane = await screen.findByRole("region", { name: "This alert" });
    expect(within(pane).getByText("Pick an alert.")).toBeVisible();
  });

  it("says nothing is muted, and says so in place when the mutes cannot be read", async () => {
    await renderAt("/alerts#state=muted", (url) => (isMutes(url) ? json([]) : null));
    expect(await screen.findByText("Nothing is muted.")).toBeVisible();
  });

  it("keeps the mutes on screen when a refresh of them fails", async () => {
    const mute = {
      mute_id: "m1",
      kind: "rule",
      subject: "r1",
      title: "Failed logons",
      until: "2026-12-01T00:00:00Z",
      created_by: "alice",
      created_at: "2026-11-01T00:00:00Z",
    };
    let reads = 0;
    const spy = await renderAt("/alerts#state=muted", (url) =>
      isMutes(url)
        ? reads++ === 0
          ? json([mute])
          : json({ error: { code: "internal", message: "It broke" } }, 500)
        : null,
    );
    // Unmute answers, and the read that follows it fails: the row stays, with no error
    // in its place.
    const real = spy.getMockImplementation() as typeof fetch;
    spy.mockImplementation(async (url, init) =>
      init?.method === "DELETE" ? new Response(null, { status: 204 }) : real(url, init),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Unmute Failed logons" }));
    await waitFor(() => expect(reads).toBeGreaterThan(1));
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByRole("button", { name: "Unmute Failed logons" })).toBeVisible();
    expect(screen.queryByText(/^Mutes did not load/)).toBeNull();
  });

  it("asks the server for the mutes of the window and marks the ones that ended", async () => {
    const mute = (id: string, active: boolean) => ({
      mute_id: id,
      kind: "rule",
      subject: id,
      title: active ? "Failed logons" : "Old noise",
      until: active ? "2099-01-01T00:00:00Z" : "2026-11-10T00:00:00Z",
      created_at: "2026-11-01T00:00:00Z",
      created_by: "alice",
      active,
      ended_at: active ? null : "2026-11-09T00:00:00Z",
    });
    const asked: string[] = [];
    await renderAt("/alerts#state=muted", (url) => {
      if (!isMutes(url)) return null;
      asked.push(url);
      return json([mute("m1", true), mute("m2", false)]);
    });
    // In force: until, with Unmute. Ended in the window: ended, and nothing to unmute.
    const live = (await screen.findByText("Failed logons")).closest("li") as HTMLElement;
    expect(live).toHaveTextContent(/until /);
    expect(within(live).getByRole("button", { name: "Unmute Failed logons" })).toBeVisible();
    const ended = screen.getByText("Old noise").closest("li") as HTMLElement;
    expect(ended).toHaveTextContent(/ended /);
    expect(within(ended).queryByRole("button")).toBeNull();
    // The default window is the last 7 days: a start and no end.
    const first = new URL(asked[0] as string, "http://x");
    expect(first.searchParams.get("ended")).toBe("true");
    expect(first.searchParams.get("to")).toBeNull();
    const from = Date.parse(String(first.searchParams.get("from")));
    expect(Date.now() - from).toBeGreaterThan(6.9 * 86_400_000);
    expect(Date.now() - from).toBeLessThan(7.1 * 86_400_000);
  });

  it("says a time window has no closed alerts, keeps the server's order, and notes a capped list", async () => {
    const asked: string[] = [];
    const item = (id: string, severity: string | null, closed: string) => ({
      item_id: id,
      kind: "rule",
      subject: id,
      title: `Alert ${id}`,
      ref_id: null,
      detail: "",
      why: null,
      count: null,
      sources: [],
      range_start: null,
      range_end: null,
      created_at: "2026-11-01T00:00:00Z",
      state: "closed",
      closed_at: closed,
      closed_by: "alice",
      close_reason: "expected",
      close_reason_label: "Expected",
      note: null,
      resolved: null,
      schedule_id: null,
      severity,
      people: [],
      devices: [],
      muted_until: null,
      history: [],
    });
    let reply: unknown = empty;
    await renderAt("/alerts#state=closed", (url) => {
      if (!isList(url) || !url.includes("state=closed")) return null;
      asked.push(url);
      return json(reply);
    });
    expect(await screen.findByText("No alerts closed in this time window.")).toBeVisible();
    // The window went to the server: a start seven days back and no end.
    const first = new URL(asked[0] as string, "http://x");
    expect(first.searchParams.get("closed_to")).toBeNull();
    const from = Date.parse(String(first.searchParams.get("closed_from")));
    expect(Date.now() - from).toBeGreaterThan(6.9 * 86_400_000);
    expect(Date.now() - from).toBeLessThan(7.1 * 86_400_000);
    // Newest closed first as the server sent them, not High first; and the cap is said.
    reply = {
      ...empty,
      capped: true,
      items: [item("a1", null, "2026-11-12T10:00:00Z"), item("a2", "high", "2026-11-11T10:00:00Z")],
    };
    await userEvent.click(
      within(screen.getByRole("group", { name: "Time" })).getByRole("button", { name: "30 days" }),
    );
    const list = await screen.findByRole("list", { name: "Alert list" });
    const titles = within(list)
      .getAllByRole("button")
      .map((b) => b.textContent ?? "")
      .filter((t) => t.includes("Alert a"));
    expect(titles[0]).toContain("Alert a1");
    expect(titles[1]).toContain("Alert a2");
    expect(within(list).getByText(/^Only the most recently closed are listed\./)).toBeVisible();
  });

  it("says a closed list is empty in its own words", async () => {
    // Every close time kept (Custom with no dates): there are none at all.
    await renderAt("/alerts#state=closed&time=custom", (url) => (isList(url) ? json(empty) : null));
    expect(await screen.findByText("No closed alerts.")).toBeVisible();
    expect(screen.queryByText(/^No open alerts/)).toBeNull();
  });

  it("does not call a failed read of the mutes nothing muted", async () => {
    await renderAt("/alerts#state=muted", (url) =>
      isMutes(url) ? json({ error: { code: "internal", message: "It broke" } }, 500) : null,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/^Mutes did not load: /);
    expect(screen.queryByText("Nothing is muted.")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  });
});

describe("Dashboard: the states of the page (redesign build row 14)", () => {
  it("says there are no panels, with one action that goes to Schedules", async () => {
    await renderAt("/dashboard", (url) => (url.endsWith("/api/dashboards") ? json([]) : null));
    const title = await screen.findByText("No panels yet.");
    const box = title.closest("[data-empty]") as HTMLElement;
    expect(box).toHaveAttribute("data-empty", "not-set-up");
    expect(within(box).getAllByRole("button")).toHaveLength(1);
    await userEvent.click(within(box).getByRole("button", { name: "Go to Schedules" }));
    expect(window.location.pathname).toBe("/alerts/schedules");
  });

  it("holds the place of a section and of AI Watch while they load", async () => {
    const never = new Promise<Response>(() => undefined);
    // A Microsoft 365 source and a file source: every tile and section is drawn.
    const status = { state: "reading", files: 1, last_pass_at: null, last_event_at: null };
    const sources = [
      { source_id: "m365_signin", kind: "m365", template_id: "m365_signin", status },
      { source_id: "linux_sshd", kind: "file", template_id: "linux_sshd", status },
    ];
    await renderAt("/dashboard", (url) =>
      url.includes("/api/dashboard/sections") || url.includes("/api/ai/watch/summary")
        ? never
        : /\/api\/sources(\?|$)/.test(url)
          ? json(sources)
          : null,
    );
    expect((await screen.findAllByRole("status", { name: "Loading AI Watch" }))[0]).toBeVisible();
    // Each section in its final place, titled, its numbers still on the way (item 27).
    for (const name of ["AI Watch", "Identity", "Attacks and access", "Detections"])
      expect(screen.getByRole("region", { name })).toHaveAttribute("data-card", "section");
    expect(
      (
        await screen.findAllByRole("status", {
          name: /^Loading (Identity|Attacks and access|Detections)$/,
        })
      ).length,
    ).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "Key numbers" })).toHaveAttribute("data-tiles", "5");
  });
});
