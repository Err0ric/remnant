import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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
    expect(within(panel).getByText("12 is above 10")).toBeInTheDocument();
    expect(
      within(panel).getByRole("img", { name: "Counts of the last 2 runs" }),
    ).toBeInTheDocument();
    expect(await within(panel).findByText("203.0.113.9")).toBeInTheDocument();
    const restricted = screen.getByRole("region", { name: "Windows failures" });
    expect(within(restricted).getByText(/Restricted/)).toBeInTheDocument();
    expect(within(restricted).queryByRole("table")).toBeNull();
  });

  it("opens a scheduled search in Search with its range and parameters filled in", async () => {
    const spy = await renderAt("/dashboard");
    const panel = await screen.findByRole("region", { name: "Failed SSH daily" });
    await userEvent.click(await within(panel).findByRole("button", { name: "Open in Search" }));
    await vi.waitFor(() => expect(window.location.pathname).toBe("/search"));
    await vi.waitFor(() =>
      expect(sent(spy, "POST", (u) => u.endsWith("/api/query")).map((b) => b?.sql)).toContain(
        "SELECT 1 LIMIT 5",
      ),
    );
  });
});

describe("Schedules", () => {
  it("creates a schedule from a preset with a threshold", async () => {
    const spy = await renderAt("/schedules");
    await userEvent.click(await screen.findByRole("button", { name: "New schedule" }));
    const form = screen.getByRole("form", { name: "New schedule" });
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

  it("opens the form with a saved search chosen from Saved searches", async () => {
    await renderAt("/saved");
    await userEvent.click(
      await screen.findByRole("button", { name: "Schedule Failed SSH by source" }),
    );
    await vi.waitFor(() => expect(window.location.pathname).toBe("/schedules"));
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
    await vi.waitFor(() => expect(window.location.pathname).toBe("/schedules"));
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
