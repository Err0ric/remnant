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
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
  return spy;
}

afterEach(() => vi.restoreAllMocks());

describe("Microsoft 365 as views of Logs (ADR-0052 section 3.3, redesign build row 9)", () => {
  it("has no area: the Sign-ins view is a page of Logs, with every number openable", async () => {
    await renderAt("/investigate/views");
    const summary = await screen.findByRole("region", { name: "Summary" });
    const rail = screen.getByRole("navigation", { name: "Primary" });
    expect(within(rail).queryByText("Microsoft 365")).toBeNull();
    expect(within(rail).getByRole("link", { name: "Logs" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("heading", { level: 1, name: "Logs" })).toBeVisible();
    expect(screen.queryByRole("navigation", { name: "Microsoft 365 tabs" })).toBeNull();
    // The tabs are those of Logs, and none of them is this view.
    const tabs = screen.getByRole("navigation", { name: "Logs tabs" });
    expect(within(tabs).queryByRole("link", { current: "page" })).toBeNull();
    for (const card of document.querySelectorAll<HTMLElement>("[data-kpi]")) {
      if (/not set|Set approved countries/i.test(card.textContent ?? "")) continue;
      expect(card.querySelector("[data-drill]"), card.dataset.kpi).not.toBeNull();
    }
    const outcomes = screen.getByRole("region", { name: "Sign-in outcomes" });
    expect(within(outcomes).getByRole("img", { name: /12 failed/ })).toHaveAttribute("data-drill");
    // The list of the view is under the summary.
    expect(await screen.findByRole("region", { name: "Sign-ins: Real failures" })).toBeVisible();
    expect(within(summary).getByTitle("Open 31 events in Logs")).toBeVisible();
    await userEvent.click(within(summary).getByTitle("Open 12 failed sign-ins in Logs"));
    await waitFor(() => expect(window.location.pathname).toBe("/investigate/logs"));
    expect(
      await screen.findByText(/^From Logs > Microsoft 365 sign-ins > Failed sign-ins, Oct 24/),
    ).toBeVisible();
  });

  it("gives an app name the card's free space, cut in the middle, whole in its title (D257)", async () => {
    await renderAt("/investigate/views");
    const apps = await screen.findByRole("table", { name: "Apps signed in to" });
    expect(apps).toHaveClass("table-fixed");
    expect([...apps.querySelectorAll("col")].map((c) => c.className)).toEqual(["", "w-24"]);
    const teams = within(apps).getByRole("button", { name: "Microsoft Teams" });
    expect(teams).toHaveAttribute("title", "Microsoft Teams\nOpen 200 events in Logs");
    expect(teams.querySelector("[data-truncate]")).toHaveAttribute("data-truncate", "name");
    expect(teams.querySelector('[data-part="tail"]')?.textContent).toBe("ft Teams");
  });

  it("opens the views from one Views menu, on every tab of Logs", async () => {
    await renderAt("/investigate/saved");
    await screen.findByRole("heading", { level: 1, name: "Logs" });
    await userEvent.click(screen.getByRole("button", { name: "Views" }));
    const menu = screen.getByRole("menu");
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((i) => i.textContent),
    ).toEqual(["Search", "Microsoft 365 sign-ins", "Microsoft 365 mail", "Microsoft 365 admin"]);
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Microsoft 365 mail" }));
    expect(window.location.pathname).toBe("/investigate/views/mail");
    expect(await screen.findByRole("heading", { level: 1, name: "Logs" })).toBeVisible();
    // The open view is marked in the menu, and the first item goes back to Logs itself.
    await userEvent.click(screen.getByRole("button", { name: "Views" }));
    expect(screen.getByRole("menuitem", { name: "Microsoft 365 mail" })).toBeDisabled();
    await userEvent.click(screen.getByRole("menuitem", { name: "Search" }));
    expect(window.location.pathname).toBe("/investigate/logs");
  });

  it("shows the Views menu to an Auditor who may not run SQL, on Saved searches", async () => {
    window.history.replaceState(null, "", "/investigate/saved");
    mockApi("Codename", { mode: "login", signedIn: true, role: "auditor" });
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
    // With one tab left, the page is titled by it and has no tab strip.
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Saved searches");
    expect(screen.queryByRole("link", { name: "Search" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Views" }));
    const items = screen.getAllByRole("menuitem");
    // No Search for this person: the first item is the tab they are on, so it is disabled.
    expect(items.map((i) => i.textContent)).toEqual([
      "Saved searches",
      "Microsoft 365 sign-ins",
      "Microsoft 365 mail",
      "Microsoft 365 admin",
    ]);
    expect(items[0]).toBeDisabled();
    await userEvent.click(items[2] as HTMLElement);
    expect(window.location.pathname).toBe("/investigate/views/mail");
    await waitFor(() =>
      expect(document.querySelectorAll("section[aria-label]").length).toBeGreaterThan(0),
    );
  });

  it.each([
    ["/m365", "/investigate/views"],
    ["/m365/overview", "/investigate/views"],
    ["/m365/sign-ins", "/investigate/views"],
    ["/m365#sign-ins", "/investigate/views"],
    ["/m365/mail", "/investigate/views/mail"],
    ["/m365#mail", "/investigate/views/mail"],
    ["/m365/admin", "/investigate/views/admin"],
    ["/m365/apps", "/ai/inventory#type=m365_app"],
    ["/m365#apps", "/ai/inventory#type=m365_app"],
    ["/m365/mail?from=mail", "/investigate/views/mail?from=mail"],
  ])("sends the old address %s to %s", async (old, now) => {
    const { canonical } = await import("@/lib/route");
    window.history.replaceState(null, "", old);
    expect(canonical()).toBe(now);
  });

  it("opens the Inventory on Microsoft 365 apps from the old Apps address", async () => {
    await renderAt("/m365/apps");
    await waitFor(() =>
      expect(window.location.pathname + window.location.hash).toBe("/ai/inventory#type=m365_app"),
    );
    const card = await screen.findByRole("region", { name: "AI inventory" });
    await waitFor(() =>
      expect(within(card).getByRole("combobox", { name: "Type" })).toHaveValue("m365_app"),
    );
  });

  it("says what is missing when there is no Microsoft 365 source", async () => {
    window.history.replaceState(null, "", "/investigate/views/mail");
    const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "analyst" });
    const real = spy.getMockImplementation() as typeof fetch;
    spy.mockImplementation(async (url, init) => {
      const res = await real(url, init);
      if (!String(url).includes("/api/m365/overview")) return res;
      const body = await res.json();
      return new Response(JSON.stringify({ ...body, has_source: false }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
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
    const title = await screen.findByText("Needs a Microsoft 365 source");
    const box = title.closest("[data-empty]") as HTMLElement;
    expect(box).toHaveAttribute("data-empty", "not-set-up");
    await userEvent.click(within(box).getByRole("button", { name: "Add a source" }));
    expect(window.location.pathname).toBe("/sources");
  });

  it("lists a tab's events over the page window", async () => {
    const spy = await renderAt("/m365/sign-ins");
    await screen.findByRole("region", { name: "Sign-ins: Real failures" });
    // The server builds and runs the list; the page sends its name and window, never SQL
    // (owner, 2026-11-08).
    await waitFor(() => {
      const urls = spy.mock.calls
        .map(([u]) => String(u))
        .filter((u) => u.includes("/api/m365/list?"));
      expect(urls.some((u) => u.includes("name=sign_ins") && u.includes("start=2026-10-24"))).toBe(
        true,
      );
    });
    expect(spy.mock.calls.some(([u]) => String(u).endsWith("/api/query"))).toBe(false);
  });

  it("names the top user and app of each spike in the tooltip (owner 2026-10-31)", async () => {
    await renderAt("/investigate/views");
    const outcomes = await screen.findByRole("region", { name: "Sign-in outcomes" });
    const chart = within(outcomes).getByRole("img", { name: /^Failed sign-ins by class/ });
    chart.focus();
    await userEvent.keyboard("{Home}{ArrowRight}{ArrowRight}{ArrowRight}");
    const tip = within(outcomes).getByRole("tooltip");
    expect(tip).toHaveTextContent("Top user svc-backup@example.com (6)");
    expect(tip).toHaveTextContent("Top app Office 365 Exchange Online (6)");
  });
});

describe("Failed sign-ins by class (D158)", () => {
  it("counts real failures, names the rest, and says how it is counted", async () => {
    await renderAt("/investigate/views");
    const overview = await screen.findByRole("region", { name: "Summary" });
    const card = overview.querySelector<HTMLElement>('[data-kpi="Failed sign-ins"]');
    expect(card).not.toBeNull();
    expect(
      within(card!).getByText("+ 37 interrupted or expired, 3 other (not counted)"),
    ).toBeVisible();
    const about = await within(card!).findByRole("img", {
      name: /50074 counted as failed \(shipped: interrupted\)/,
    });
    expect(about.getAttribute("title")).toMatch(/^How this is counted: Counts real failures only/);
    expect(about.getAttribute("title")).toMatch(
      /53003 is also shown on its own as Blocked by policy/,
    );
    expect(overview.querySelector('[data-kpi="Blocked by policy"]')).not.toBeNull();
    const outcomes = screen.getByRole("region", { name: "Sign-in outcomes" });
    for (const label of ["Failed", "Interrupted", "Expired", "Other"]) {
      expect(outcomes.querySelector(`[data-kpi="${label}"]`), label).not.toBeNull();
    }
  });

  it("filters Sign-ins by class and by who signed in, real failures first", async () => {
    const spy = await renderAt("/m365/sign-ins");
    const list = await screen.findByRole("region", { name: "Sign-ins: Real failures" });
    const sent = () =>
      spy.mock.calls.map(([u]) => String(u)).filter((u) => u.includes("/api/m365/list?"));
    await waitFor(() =>
      expect(sent().some((q) => q.includes("cls=failed") && q.includes("mode=all"))).toBe(true),
    );
    await userEvent.click(within(list).getByRole("button", { name: "Expired" }));
    await userEvent.click(
      within(screen.getByRole("region", { name: "Sign-ins: Expired" })).getByRole("button", {
        name: "Non-interactive",
      }),
    );
    await waitFor(() =>
      expect(
        sent().some((q) => q.includes("cls=expired") && q.includes("mode=noninteractive")),
      ).toBe(true),
    );
    await userEvent.click(screen.getByRole("button", { name: "All" }));
    expect(await screen.findByRole("region", { name: "Sign-ins" })).toBeVisible();
  });
});

describe("notCountedText", () => {
  it("names other apart only when there is some", async () => {
    const { notCountedText } = await import("@/features/m365/signInCounting");
    expect(notCountedText(12)).toBe("+ 12 interrupted or expired (not counted)");
    expect(notCountedText(12, 2)).toBe("+ 10 interrupted or expired, 2 other (not counted)");
    expect(notCountedText(2, 2)).toBe("+ 2 other (not counted)");
  });
});

describe("Mail rules (D132)", () => {
  it("groups one person's burst into one line, risky bursts first", async () => {
    const { bursts, burstLine } = await import("@/features/m365/MailRules");
    const columns = ["time", "person", "rule", "class", "risky", "severity", "burst", "event_id"];
    const organizing = Array.from({ length: 60 }, (_, i) => [
      `2026-10-${i < 30 ? 29 : 30}T19:${String(i % 30).padStart(2, "0")}:00+00:00`,
      "dana@example.com",
      `From co${i}`,
      "organizing",
      false,
      "low",
      "dana@example.com|0",
      `e${i}`,
    ]);
    const junk = [0, 1].map((i) => [
      "2026-10-30T20:0" + i + ":00+00:00",
      "dana@example.com",
      `j${i}`,
      "hiding",
      true,
      "medium",
      "dana@example.com|0",
      `j${i}`,
    ]);
    const other = [
      [
        "2026-10-31T09:00:00+00:00",
        "sam@example.com",
        "x",
        "organizing",
        false,
        "low",
        "sam@example.com|0",
        "s1",
      ],
    ];
    const got = bursts({
      columns,
      rows: [...junk, ...organizing, ...other],
      row_count: 63,
      truncated: false,
      elapsed_ms: 0,
      executed_sql: "",
      sources: ["m365"],
    });
    expect(got.map((b) => b.person)).toEqual(["dana@example.com", "sam@example.com"]);
    expect(got[0]!.risky).toBe(2);
    expect(burstLine(got[0]!)).toMatch(
      /^dana@example\.com created 62 rules Oct (29|30) to Oct (30|31): 60 organizing, 2 hiding$/,
    );
    expect(burstLine(got[1]!)).toMatch(/^sam@example\.com created 1 rule Oct 31: 1 organizing$/);
  });
});
