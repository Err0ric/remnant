import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { timesNote } from "@/lib/localTime";
import { SOURCE, mockApi } from "./mockApi";

/** The state where the old numbers disagreed (fix list 2026-11-16 item 12): two sources with
 * a problem (linux_sshd a gap, win_dc an error, by the server's rule) and one enrichment feed
 * that needs a look (GeoIP ASN, not installed while automatic updates are on). Before, the
 * Sources tab said 3 and Problems said 2, with nothing saying why. */
async function renderHealth(damagedOnly = false) {
  window.history.replaceState(null, "", "/health");
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
  const base = spy.getMockImplementation() as typeof fetch;
  const json = (body: unknown) =>
    new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  spy.mockImplementation(async (input, init) => {
    const u = String(input);
    const get = (init?.method ?? "GET") === "GET";
    if (get && u.endsWith("/api/sources"))
      return json([SOURCE, { ...SOURCE, source_id: "win_dc" }, { ...SOURCE, source_id: "dns" }]);
    if (damagedOnly && get && u.endsWith("/api/overview")) {
      // Every source healthy, and two damaged lake files moved aside.
      const body = (await (await base(input, init)).json()) as {
        sources: Record<string, unknown>[];
      };
      const sources = body.sources.map((x) => ({
        ...x,
        state: "reading",
        error: null,
        quiet_since: null,
        condition: "healthy",
        problem: null,
      }));
      return json({ ...body, sources, damaged_files: 2 });
    }
    if (damagedOnly && get && u.endsWith("/api/enrichment")) return base(input, init);
    if (get && u.endsWith("/api/enrichment")) {
      const body = (await (await base(input, init)).json()) as Record<string, unknown>;
      return json({ ...body, auto_update: true });
    }
    return base(input, init);
  });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
}

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

const n = (el: Element | null | undefined) => Number(/\d+/.exec(el?.textContent ?? "")?.[0]);

describe("Health counts from one rule (fix list 2026-11-16 item 12)", () => {
  it("agrees everywhere: the tab, Problems, the rows, the other type, and the rail", async () => {
    await renderHealth();
    const tabs = await screen.findByRole("navigation", { name: "Health tabs" });
    const sourcesTab = within(tabs).getByRole("link", { name: /^Sources/ });
    const status = screen.getByRole("group", { name: "Status" });
    const problems = () => within(status).getByRole("button", { name: /^Problems/ });
    // Every part judged: the tab's count, and the link to the feed that needs a look.
    const elsewhere = await screen.findByRole("button", {
      name: "Show 1 problem in Enrichment feeds",
    });
    await vi.waitFor(() => expect(sourcesTab.querySelector("[data-problems]")).not.toBeNull());
    const badge = sourcesTab.querySelector("[data-problems]");

    // The tab counts every type on it (D255) and says so; the numbers on the page add up.
    expect(n(badge)).toBe(3);
    expect(badge).toHaveAttribute("title", "3 need attention: 2 in Events, 1 in Enrichment feeds");
    expect(n(problems())).toBe(2);
    expect(n(problems()) + n(elsewhere)).toBe(n(badge));

    // Problems lists exactly as many rows as its count.
    await userEvent.click(problems());
    const flow = await screen.findByRole("list", { name: "Sources" });
    expect(within(flow).getAllByRole("listitem")).toHaveLength(2);

    // The rail's dot counts the same sources, by the same server rule.
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(
      within(nav).getByRole("link", { name: "Health: 2 sources need attention, 1 unhealthy" }),
    ).toBeInTheDocument();
    expect(elsewhere).toHaveClass("text-accent-text", "hover:underline");

    // The link opens the other type, where Problems is that one feed, and the way back.
    await userEvent.click(elsewhere);
    expect(window.location.hash).toContain("type=enrichment");
    await vi.waitFor(() => expect(n(problems())).toBe(1));
    // The reverse link: from the feeds back to the sources with a problem.
    const back = screen.getByRole("button", { name: "Show 2 problems in Events" });
    expect(back).toHaveClass("text-accent-text");
    await userEvent.click(back);
    expect(window.location.hash).not.toContain("type=enrichment");
    await vi.waitFor(() => expect(n(problems())).toBe(2));
  });
});

describe("The damaged-files notice counts the same everywhere (review of 637)", () => {
  it("is the tab's one problem, Problems' one row, the link's target, and the rail's dot", async () => {
    await renderHealth(true);
    const tabs = await screen.findByRole("navigation", { name: "Health tabs" });
    const sourcesTab = within(tabs).getByRole("link", { name: /^Sources/ });
    await vi.waitFor(() => expect(sourcesTab.querySelector("[data-problems]")).not.toBeNull());
    const badge = sourcesTab.querySelector("[data-problems]");
    expect(n(badge)).toBe(1);
    expect(badge).toHaveAttribute("title", "1 needs attention: the data folder");
    const status = screen.getByRole("group", { name: "Status" });
    const problems = within(status).getByRole("button", { name: /^Problems/ });
    expect(n(problems)).toBe(1);
    await userEvent.click(problems);
    const flow = await screen.findByRole("list", { name: "Sources" });
    expect(within(flow).queryAllByRole("listitem")).toHaveLength(0); // no source row
    expect(screen.getByText(/^Data folder: 2 damaged files/)).toBeVisible(); // the one row
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const health = within(nav).getByRole("link", {
      name: "Health: 2 damaged files in the data folder",
    });
    expect(health.querySelector("[data-health-dot]")).toHaveClass("bg-warn");
    // From the feeds, the link names it and opens Events, where the notice is.
    await userEvent.click(within(status).getByRole("button", { name: /^All/ }));
    await userEvent.click(screen.getByRole("combobox", { name: "Type" }));
    await userEvent.click(await screen.findByRole("option", { name: "Enrichment feeds" }));
    expect(window.location.hash).toContain("type=enrichment");
    await userEvent.click(await screen.findByRole("button", { name: "Show 1 problem in Events" }));
    expect(window.location.hash).not.toContain("type=enrichment");
  });
});

describe("The rail dot's words (D265)", () => {
  it("has two forms for sources, and names damaged files apart", async () => {
    const { healthWords } = await import("@/features/health/flow");
    expect(healthWords({ count: 0, unhealthy: 0, damaged: 0 })).toBe("");
    expect(healthWords({ count: 1, unhealthy: 0, damaged: 0 })).toBe(
      "Health: 1 source needs attention",
    );
    // Every problem source red: still the second form, never a third.
    expect(healthWords({ count: 2, unhealthy: 2, damaged: 0 })).toBe(
      "Health: 2 sources need attention, 2 unhealthy",
    );
    expect(healthWords({ count: 2, unhealthy: 1, damaged: 1 })).toBe(
      "Health: 2 sources need attention, 1 unhealthy; 1 damaged file in the data folder",
    );
  });
});

describe("The times note (fix list 2026-11-16 item S5)", () => {
  it("offers the UTC hover only where it says something", () => {
    expect(timesNote("UTC")).toBe("Times in UTC.");
    expect(timesNote("PDT")).toBe("Times in PDT; hover for UTC.");
  });
});
