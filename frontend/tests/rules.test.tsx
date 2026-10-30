import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

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

function bodies(spy: ReturnType<typeof mockApi>, test: (u: string) => boolean) {
  return spy.mock.calls
    .filter(([u, init]) => test(String(u)) && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)) as Record<string, unknown>);
}

afterEach(() => vi.restoreAllMocks());

describe("Detection rules", () => {
  it("lists rules with their authors, and says when none is stated", async () => {
    await renderAt("/rules");
    const table = await screen.findByRole("table", { name: "Detection rules" });
    expect(await within(table).findByText("Failed logon burst")).toBeInTheDocument();
    expect(within(table).getByText("Jane Doe")).toBeInTheDocument();
    expect(within(table).getByText("author not stated")).toBeInTheDocument();
    expect(within(table).getAllByText("windows / security")).toHaveLength(2);
    expect(within(table).getByText("win_dc")).toBeInTheDocument();
    expect(within(table).getByText("no data")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: "With data only" }));
    expect(within(table).queryByText("Disabled example")).toBeNull();
  });

  it("runs a rule, shows matches with attribution, and opens them in Search", async () => {
    const spy = await renderAt("/rules");
    const table = await screen.findByRole("table", { name: "Detection rules" });
    await userEvent.click(
      await within(table).findByRole("button", { name: "Run Failed logon burst" }),
    );
    const panel = await screen.findByRole("region", { name: "Rule run" });
    expect(within(panel).getByText("Failed logon burst")).toBeInTheDocument();
    expect(within(panel).getByText("by Jane Doe")).toBeInTheDocument();
    expect(await within(panel).findByRole("table", { name: "Matches" })).toBeInTheDocument();
    const [body] = bodies(spy, (u) => u.endsWith("/api/rules/r1/run"));
    expect(Date.parse(String(body?.end)) - Date.parse(String(body?.start))).toBe(86_400_000);
    await userEvent.click(within(panel).getByRole("button", { name: "Open in Search" }));
    await vi.waitFor(() => expect(window.location.pathname).toBe("/investigate/search"));
    const seeded = await vi.waitFor(() => {
      const q = bodies(spy, (u) => u.endsWith("/api/query")).find((b) =>
        String(b.sql).includes("WHERE event_id IN"),
      );
      expect(q).toBeDefined();
      return q;
    });
    expect(String(seeded?.sql)).toContain("('01a126d0-7c4f-7012-b6b0-e17359887d5f')");
    expect(seeded?.start).toBeUndefined(); // all time
  });

  it("enables selected rules and shows import refusals with reasons", async () => {
    const spy = await renderAt("/rules");
    const table = await screen.findByRole("table", { name: "Detection rules" });
    await userEvent.click(
      await within(table).findByRole("checkbox", { name: "Select Disabled example" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Enable selected (1)" }));
    await vi.waitFor(() =>
      expect(bodies(spy, (u) => u.endsWith("/api/rules/enabled"))).toEqual([
        { rule_ids: ["r2"], enabled: true },
      ]),
    );
    await userEvent.click(screen.getByRole("button", { name: "Import rules" }));
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    const refused = await screen.findByRole("table", { name: "Refused rules" });
    expect(within(refused).getByText(/not supported yet/)).toBeInTheDocument();
  });

  it("schedules an enabled rule from its row", async () => {
    await renderAt("/rules");
    const table = await screen.findByRole("table", { name: "Detection rules" });
    expect(within(table).queryByRole("button", { name: "Schedule Disabled example" })).toBeNull();
    await userEvent.click(
      await within(table).findByRole("button", { name: "Schedule Failed logon burst" }),
    );
    await vi.waitFor(() => expect(window.location.pathname).toBe("/alerts/schedules"));
    const form = await screen.findByRole("form", { name: "New schedule" });
    expect(within(form).getByLabelText("Runs")).toHaveValue("rule");
    await vi.waitFor(() => expect(within(form).getByLabelText("Rule")).toHaveValue("r1"));
  });

  it("lets auditors read but not run, import, or select", async () => {
    await renderAt("/rules", { mode: "login", signedIn: true, role: "auditor" });
    const table = await screen.findByRole("table", { name: "Detection rules" });
    await within(table).findByText("Failed logon burst");
    expect(within(table).queryByRole("button", { name: /^Run / })).toBeNull();
    expect(within(table).queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Import rules" })).toBeNull();
  });

  it("shows rule YAML as text and keeps disabled rules unrunnable for analysts", async () => {
    await renderAt("/rules", { mode: "login", signedIn: true, role: "analyst" });
    const table = await screen.findByRole("table", { name: "Detection rules" });
    expect(
      await within(table).findByRole("button", { name: "Run Disabled example" }),
    ).toBeDisabled();
    await userEvent.click(within(table).getByRole("button", { name: "View Failed logon burst" }));
    const src = await screen.findByRole("region", { name: "Rule source" });
    expect(await within(src).findByText(/<b>not markup<\/b>/)).toBeInTheDocument();
    expect(src.querySelector("b")).toBeNull();
  });

  it("schedules every selected rule at once with one set of settings (F58)", async () => {
    const spy = await renderAt("/rules");
    const table = await screen.findByRole("table", { name: "Detection rules" });
    await userEvent.click(await within(table).findByRole("checkbox", { name: "Select all shown" }));
    await userEvent.click(screen.getByRole("button", { name: "Schedule selected" }));
    const form = await screen.findByRole("form", { name: "Schedule selected rules" });
    expect(within(form).getByText("1 not enabled will be skipped.")).toBeVisible();
    await userEvent.click(await within(form).findByRole("checkbox", { name: /SOC/ }));
    await userEvent.click(within(form).getByRole("button", { name: "Schedule 1 rule" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Scheduled 1 rule. Skipped 1.");
    const made = bodies(spy, (u) => u.endsWith("/api/schedules"));
    expect(made).toHaveLength(1);
    expect(made[0]).toMatchObject({
      kind: "rule",
      target_id: "r1",
      cron: "hourly",
      add_panel: false,
    });
    expect((made[0]?.target_ids as string[]).length).toBe(1);
  });
});
