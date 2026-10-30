import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fillSql } from "@/features/schedules/schedule";
import { mockApi, type MockAuth } from "./mockApi";

async function renderAt(
  path: string,
  auth: MockAuth = { mode: "login", signedIn: true, role: "analyst" },
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

function sent(spy: ReturnType<typeof mockApi>, method: string, test: (u: string) => boolean) {
  return spy.mock.calls
    .filter(([u, init]) => test(String(u)) && init?.method === method)
    .map(([, init]) => JSON.parse(String(init?.body ?? "null")) as Record<string, unknown> | null);
}

afterEach(() => vi.restoreAllMocks());

describe("Dashboard", () => {
  it("shows count, flag, trend, and top rows, and hides restricted results", async () => {
    await renderAt("/dashboard");
    const panel = await screen.findByRole("region", { name: "Failed SSH daily" });
    expect(within(panel).getByText("12")).toBeInTheDocument();
    expect(within(panel).getByText("Flagged")).toBeInTheDocument();
    // Plain words, from what a row is (the first column is an address).
    expect(await within(panel).findByText("12 addresses over threshold (10)")).toBeInTheDocument();
    // Two runs are not a trend yet.
    expect(within(panel).queryByRole("img", { name: /Counts of the last/ })).toBeNull();
    expect(await within(panel).findByText("203.0.113.9")).toBeInTheDocument();
    const restricted = screen.getByRole("region", { name: "Windows failures" });
    expect(within(restricted).getByText(/Restricted/)).toBeInTheDocument();
    expect(within(restricted).queryByRole("table")).toBeNull();
  });

  it("opens a scheduled search in Search with its range and parameters filled in", async () => {
    const spy = await renderAt("/dashboard");
    const panel = await screen.findByRole("region", { name: "Failed SSH daily" });
    await userEvent.click(await within(panel).findByRole("button", { name: "Open in Search" }));
    await vi.waitFor(() => expect(window.location.pathname).toBe("/investigate/search"));
    await vi.waitFor(() =>
      expect(sent(spy, "POST", (u) => u.endsWith("/api/query")).map((b) => b?.sql)).toContain(
        "SELECT 1 LIMIT 5",
      ),
    );
  });
});

describe("Dashboard panels (trial finding, ADR-0034)", () => {
  it("lets the dashboard owner set size and switch a summary result to bars", async () => {
    const spy = await renderAt("/dashboard");
    const panel = await screen.findByRole("region", { name: "Failed SSH daily" });
    expect(within(panel).queryByRole("group", { name: /Size of/ })).toBeNull(); // not editing
    await userEvent.click(screen.getByRole("button", { name: "Edit layout" }));
    const size = within(panel).getByRole("group", { name: "Size of Failed SSH daily" });
    expect(within(size).getByRole("button", { name: "1/3" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await userEvent.click(within(size).getByRole("button", { name: "Full" }));
    const view = await within(panel).findByRole("group", { name: "View of Failed SSH daily" });
    await userEvent.click(within(view).getByRole("button", { name: "Bars" }));
    await vi.waitFor(() =>
      expect(sent(spy, "PUT", (u) => u.endsWith("/api/dashboards/d1/panels/s1"))).toEqual([
        { size: "full" },
        { view: "bars" },
      ]),
    );
    const bars = await within(panel).findByRole("list", { name: "Top values of Failed SSH daily" });
    expect(within(bars).getByRole("button", { name: "203.0.113.9: 9 failures" })).toBeVisible();
    expect(within(panel).queryByRole("table")).toBeNull();
  });

  it("opens the full result from a whole row", async () => {
    await renderAt("/dashboard");
    const panel = await screen.findByRole("region", { name: "Failed SSH daily" });
    const table = await within(panel).findByRole("table", { name: "Top rows of Failed SSH daily" });
    expect(within(table).getByText("203.0.113.9")).toHaveAttribute("title", "203.0.113.9");
    await userEvent.click(within(table).getByRole("button", { name: "Open row 1 in Search" }));
    await vi.waitFor(() => expect(window.location.pathname).toBe("/investigate/search"));
  });

  it("says when a source's parser changed before a run (F36)", async () => {
    await renderAt("/dashboard");
    const panel = await screen.findByRole("region", { name: "Failed SSH daily" });
    expect(within(panel).getByRole("note")).toHaveTextContent(
      "Parser changed for lin_auth at 2026-10-11 03:00 UTC (generic_syslog to linux_sshd)",
    );
  });

  it("offers no layout editing on a shared dashboard someone else owns", async () => {
    await renderAt("/dashboard");
    await userEvent.selectOptions(await screen.findByLabelText("Dashboard"), "d2");
    expect(await screen.findByRole("heading", { name: "Team", level: 1 })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Edit layout" })).toBeNull();
    // Sections have headers; a tile shows the number but no table.
    const section = screen.getByRole("region", { name: "Windows" });
    expect(within(section).getByRole("heading", { name: /Windows/ })).toBeVisible();
    const tile = within(section).getByRole("region", { name: "Windows failures" });
    expect(within(tile).getByText(/Restricted/)).toBeInTheDocument();
  });
});

describe("Dashboards at scale (ADR-0034)", () => {
  it("puts what needs me first, one line each, severity first (F62)", async () => {
    await renderAt("/dashboard");
    const banner = await screen.findByRole("region", { name: "Needs you" });
    const lines = (await within(banner).findAllByRole("row")).slice(1); // after the header
    // High first: the not-approved service and the source with errors; then the alert.
    expect(lines[0]).toHaveTextContent(/^High/);
    // The badge column is severity only; the kind is in the text (ADR-0038).
    const badges = lines.map((l) => within(l).getAllByRole("cell")[0]?.textContent);
    expect(badges.every((b) => b === "High" || b === "Medium")).toBe(true);
    // The AI Watch title already says the decision needed: no trailing reason.
    expect(
      within(banner).getByRole("link", { name: "AI Watch: New AI service: DeepSeek" }),
    ).toBeVisible();
    expect(
      within(banner).getByRole("link", { name: /^Rule: Failed logons: Count 12 is above 5/ }),
    ).toHaveAttribute("href", "/alerts#item=a1");
    expect(within(banner).getByRole("link", { name: "Source: win_dc has errors" })).toHaveAttribute(
      "href",
      "/health#source=win_dc",
    );
    expect(within(banner).getByText(/1 restricted/)).toBeVisible();
    // AI Watch comes next, then the panels, then sources in one line at the bottom.
    const watch = screen.getByRole("region", { name: "AI Watch" });
    expect(banner.compareDocumentPosition(watch) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: /^Sources: / })).toBeVisible();
  });

  it("sets the headline the panel shows, for the schedule's owner", async () => {
    const spy = await renderAt("/dashboard");
    await screen.findByRole("region", { name: "Failed SSH daily" });
    await userEvent.click(screen.getByRole("button", { name: "Edit layout" }));
    const form = await screen.findByRole("form", { name: "Headline of Failed SSH daily" });
    await userEvent.selectOptions(
      within(form).getByLabelText("Number shown for Failed SSH daily"),
      "sum",
    );
    await userEvent.selectOptions(
      await within(form).findByLabelText("Column for Failed SSH daily"),
      "failures",
    );
    await userEvent.type(
      within(form).getByLabelText("Label for Failed SSH daily"),
      "failed logins",
    );
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() =>
      expect(sent(spy, "PATCH", (u) => u.endsWith("/api/schedules/s1"))).toEqual([
        { headline_kind: "sum", headline_column: "failures", headline_label: "failed logins" },
      ]),
    );
    // Someone else's schedule on my dashboard: layout yes, headline no.
    const other = screen.getByRole("region", { name: "Windows failures" });
    expect(within(other).getByRole("group", { name: "Size of Windows failures" })).toBeVisible();
    expect(within(other).queryByRole("form", { name: /Headline of/ })).toBeNull();
  });

  it("makes a new dashboard and adds a panel to it", async () => {
    const spy = await renderAt("/dashboard");
    await screen.findByRole("region", { name: "Failed SSH daily" });
    await userEvent.click(screen.getByRole("button", { name: "New dashboard" }));
    expect(await screen.findByRole("heading", { name: "New dashboard", level: 1 })).toBeVisible();
    const settings = screen.getByRole("region", { name: "Dashboard settings" });
    await userEvent.selectOptions(within(settings).getByLabelText("Schedule to add"), "s1");
    await userEvent.click(within(settings).getByRole("button", { name: "Add panel" }));
    expect(await screen.findByRole("region", { name: "Failed SSH daily" })).toBeVisible();
    expect(sent(spy, "POST", (u) => u.endsWith("/api/dashboards"))).toEqual([
      { name: "New dashboard", shared: false },
    ]);
  });
});

describe("Schedules", () => {
  it("creates a schedule from a preset with a threshold", async () => {
    const spy = await renderAt("/schedules");
    await userEvent.click(await screen.findByRole("button", { name: "New schedule" }));
    const form = await screen.findByRole("form", { name: "New schedule" });
    await userEvent.selectOptions(within(form).getByLabelText("Saved search"), "failed_by_ip");
    await userEvent.selectOptions(within(form).getByLabelText("When"), "hourly");
    await userEvent.selectOptions(within(form).getByLabelText("Flag when"), "above");
    await userEvent.type(within(form).getByLabelText("Flag value"), "20");
    await userEvent.click(within(form).getByRole("button", { name: "Create schedule" }));
    await vi.waitFor(() =>
      expect(sent(spy, "POST", (u) => u.endsWith("/api/schedules"))).toEqual([
        {
          kind: "search",
          target_id: "failed_by_ip",
          cron: "hourly",
          lookback_minutes: null,
          shared: false,
          threshold_kind: "above",
          threshold_value: 20,
        },
      ]),
    );
  });

  it("lets owners pause and run, and shows others' schedules read-only", async () => {
    const spy = await renderAt("/schedules");
    const table = await screen.findByRole("table", { name: "Schedules" });
    await userEvent.click(
      await within(table).findByRole("button", { name: "Pause Failed SSH daily" }),
    );
    await vi.waitFor(() =>
      expect(sent(spy, "PATCH", (u) => u.includes("/api/schedules/s1"))).toEqual([
        { paused: true },
      ]),
    );
    expect(
      within(table).queryByRole("button", {
        name: /^(Run|Pause|Resume|Delete) .*Windows failures/,
      }),
    ).toBeNull();
    expect(within(table).getByText("Daily at 07:00")).toBeInTheDocument();
    expect(within(table).getByText("Since the last run")).toBeInTheDocument();
  });

  it("edits a schedule and sends only what changed", async () => {
    const spy = await renderAt("/schedules");
    const table = await screen.findByRole("table", { name: "Schedules" });
    await userEvent.click(
      await within(table).findByRole("button", { name: "Edit Failed SSH daily" }),
    );
    const form = await screen.findByRole("form", { name: "Edit Failed SSH daily" });
    await userEvent.selectOptions(within(form).getByLabelText("Time range of each run"), "60");
    await userEvent.click(within(form).getByRole("button", { name: "Save changes" }));
    await vi.waitFor(() =>
      expect(sent(spy, "PATCH", (u) => u.includes("/api/schedules/s1"))).toEqual([
        { lookback_minutes: 60 },
      ]),
    );
  });

  it("opens the form with a saved search chosen from Saved searches", async () => {
    await renderAt("/saved");
    await userEvent.click(
      await screen.findByRole("button", { name: "Schedule Failed SSH by source" }),
    );
    await vi.waitFor(() => expect(window.location.pathname).toBe("/alerts/schedules"));
    const form = await screen.findByRole("form", { name: "New schedule" });
    await vi.waitFor(() =>
      expect(within(form).getByLabelText("Saved search")).toHaveValue("failed_by_ip"),
    );
  });

  it("Schedule on Search saves first, then opens the form with that search", async () => {
    await renderAt("/search");
    await userEvent.click(await screen.findByRole("button", { name: "Schedule" }));
    const save = await screen.findByRole("form", { name: "Save search" });
    await userEvent.type(within(save).getByLabelText("Name"), "Nightly check");
    await userEvent.click(within(save).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(window.location.pathname).toBe("/alerts/schedules"));
    const form = await screen.findByRole("form", { name: "New schedule" });
    await vi.waitFor(() =>
      expect(within(form).getByLabelText("Saved search")).toHaveValue("nightly_check"),
    );
  });

  it("hides New schedule from auditors", async () => {
    await renderAt("/schedules", { mode: "login", signedIn: true, role: "auditor" });
    await screen.findByRole("table", { name: "Schedules" });
    expect(screen.queryByRole("button", { name: "New schedule" })).toBeNull();
  });
});

describe("fillSql", () => {
  it("fills range and parameters as literals and refuses missing ones", () => {
    expect(
      fillSql("x BETWEEN {{start}} AND {{ end }} AND u = {{who}}", { who: "o'brien" }, "a", "b"),
    ).toBe("x BETWEEN TIMESTAMPTZ 'a' AND TIMESTAMPTZ 'b' AND u = 'o''brien'");
    expect(fillSql("LIMIT {{top}}", {}, "a", "b")).toBeNull();
    expect(fillSql("x = {{flag}}", { flag: true }, "a", "b")).toBe("x = TRUE");
  });
});

describe("Dashboard layout (ADR-0034, owner 2026-10-22)", () => {
  function layouts(spy: ReturnType<typeof mockApi>) {
    return sent(spy, "PUT", (u) => u.endsWith("/api/dashboards/d1/layout")).map(
      (b) => (b as { sections: { name: string; schedule_ids: string[] }[] }).sections,
    );
  }

  it("moves a panel to a new section from the keyboard, then manages sections", async () => {
    const spy = await renderAt("/dashboard");
    await screen.findByRole("region", { name: "Failed SSH daily" });
    await userEvent.click(screen.getByRole("button", { name: "Edit layout" }));
    const panel = screen.getByRole("region", { name: "Windows failures" });
    await userEvent.selectOptions(
      within(panel).getByLabelText("Move Windows failures to section"),
      "\u0000new",
    );
    await userEvent.type(
      within(panel).getByLabelText("New section for Windows failures"),
      "Windows{enter}",
    );
    await vi.waitFor(() =>
      expect(layouts(spy).at(-1)).toEqual([
        { name: "", schedule_ids: ["s1"] },
        { name: "Windows", schedule_ids: ["s2"] },
      ]),
    );
    const section = await screen.findByRole("region", { name: "Windows" });
    // Add an empty section, move it up, rename it, then delete it.
    const settings = screen.getByRole("region", { name: "Dashboard settings" });
    await userEvent.type(within(settings).getByLabelText("New section name"), "Accounts");
    await userEvent.click(within(settings).getByRole("button", { name: "Add section" }));
    await screen.findByRole("region", { name: "Accounts" });
    await userEvent.click(screen.getByRole("button", { name: "Move section Accounts up" }));
    await vi.waitFor(() =>
      expect(
        layouts(spy)
          .at(-1)
          ?.map((x) => x.name),
      ).toEqual(["", "Accounts", "Windows"]),
    );
    await userEvent.click(screen.getByRole("button", { name: "Rename section Accounts" }));
    const name = screen.getByLabelText("New name for section Accounts");
    await userEvent.clear(name);
    await userEvent.type(name, "Sign-ins{enter}");
    await vi.waitFor(() =>
      expect(sent(spy, "PATCH", (u) => u.endsWith("/api/dashboards/d1/sections"))).toEqual([
        { old: "Accounts", new: "Sign-ins" },
      ]),
    );
    await userEvent.click(within(section).getByRole("button", { name: "Delete section Windows" }));
    await userEvent.click(within(section).getByRole("button", { name: "Delete section" }));
    await vi.waitFor(() =>
      expect(layouts(spy).at(-1)).toEqual([
        { name: "", schedule_ids: ["s1", "s2"] },
        { name: "Sign-ins", schedule_ids: [] },
      ]),
    );
  });

  it("drags a panel before another", async () => {
    const spy = await renderAt("/dashboard");
    await screen.findByRole("region", { name: "Failed SSH daily" });
    await userEvent.click(screen.getByRole("button", { name: "Edit layout" }));
    const second = screen.getByRole("region", { name: "Windows failures" })
      .parentElement as HTMLElement;
    const first = screen.getByRole("region", { name: "Failed SSH daily" })
      .parentElement as HTMLElement;
    const data = { setData: vi.fn(), effectAllowed: "" };
    fireEvent.dragStart(second, { dataTransfer: data });
    fireEvent.dragOver(first, { dataTransfer: data });
    fireEvent.drop(first, { dataTransfer: data });
    await vi.waitFor(() =>
      expect(layouts(spy).at(-1)).toEqual([{ name: "", schedule_ids: ["s2", "s1"] }]),
    );
  });
});
