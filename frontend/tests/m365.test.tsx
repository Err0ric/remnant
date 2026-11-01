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

describe("Microsoft 365 area (ADR-0038 section 5)", () => {
  it("sits under Connected apps and shows the Overview with every number openable", async () => {
    await renderAt("/m365");
    const overview = await screen.findByRole("region", { name: "Overview" });
    const apps = screen.getByRole("region", { name: "Connected apps" });
    expect(within(apps).getAllByText("Microsoft 365")[0]).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Microsoft 365 tabs" })).toBeVisible();
    for (const card of document.querySelectorAll<HTMLElement>("[data-kpi]")) {
      if (/not set|Set approved countries/i.test(card.textContent ?? "")) continue;
      expect(card.querySelector("[data-drill]"), card.dataset.kpi).not.toBeNull();
    }
    const outcomes = screen.getByRole("region", { name: "Sign-in outcomes" });
    expect(within(outcomes).getByRole("img", { name: /12 failed/ })).toHaveAttribute("data-drill");
    expect(within(overview).getByTitle("Open 31 events in Search")).toBeVisible();
    await userEvent.click(within(overview).getByTitle("Open 12 events in Search"));
    await waitFor(() => expect(window.location.pathname).toBe("/investigate/search"));
    expect(
      await screen.findByText(/^From Microsoft 365 > Overview > Failed sign-ins, Oct 24/),
    ).toBeVisible();
  });

  it("lists a tab's events over the page window", async () => {
    const spy = await renderAt("/m365/sign-ins");
    await screen.findByRole("region", { name: "Sign-ins" });
    await waitFor(() => {
      const bodies = spy.mock.calls
        .filter(([u, i]) => String(u).endsWith("/api/query") && i?.method === "POST")
        .map(([, i]) => JSON.parse(String(i?.body)) as { sql: string; start?: string });
      expect(bodies.some((b) => b.sql.includes("2026-10-24T00:00:00+00:00") && b.start)).toBe(true);
    });
  });

  it("names the top user and app of each spike in the tooltip (owner 2026-10-31)", async () => {
    await renderAt("/m365");
    const outcomes = await screen.findByRole("region", { name: "Sign-in outcomes" });
    const chart = within(outcomes).getByRole("img", { name: /^Interrupted and failed/ });
    chart.focus();
    await userEvent.keyboard("{Home}{ArrowRight}{ArrowRight}{ArrowRight}");
    const tip = within(outcomes).getByRole("tooltip");
    expect(tip).toHaveTextContent("Top user svc-backup@example.com (6)");
    expect(tip).toHaveTextContent("Top app Office 365 Exchange Online (6)");
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
