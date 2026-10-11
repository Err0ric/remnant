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

function posted(spy: ReturnType<typeof mockApi>, test: (u: string) => boolean) {
  return spy.mock.calls
    .filter(([u, init]) => test(String(u)) && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body ?? "null")) as Record<string, unknown> | null);
}

afterEach(() => vi.restoreAllMocks());

describe("Alert targets", () => {
  it("adds a webhook and shows its signing key once", async () => {
    const spy = await renderAt("/alert-targets");
    await userEvent.click(await screen.findByRole("button", { name: "Add target" }));
    const form = screen.getByRole("form", { name: "New alert target" });
    await userEvent.selectOptions(within(form).getByLabelText("Kind"), "webhook");
    await userEvent.type(within(form).getByLabelText("Name"), "Relay");
    await userEvent.type(within(form).getByLabelText("Webhook URL"), "http://192.168.1.50/hook");
    await userEvent.click(within(form).getByRole("button", { name: "Add target" }));
    const key = await screen.findByRole("region", { name: "Signing key" });
    expect(within(key).getByLabelText("Webhook signing key")).toHaveValue("KEY-ONCE");
    expect(posted(spy, (u) => u.endsWith("/api/alert-targets"))).toEqual([
      { name: "Relay", kind: "webhook", url: "http://192.168.1.50/hook" },
    ]);
    await userEvent.click(within(key).getByRole("button", { name: "Done" }));
    expect(screen.queryByText("KEY-ONCE")).toBeNull();
  });

  it("shows a failed test send with its reason", async () => {
    await renderAt("/alert-targets");
    const table = await screen.findByRole("table", { name: "Alert targets" });
    await userEvent.click(
      await within(table).findByRole("button", { name: "Send a test to SOC Slack" }),
    );
    expect(
      await within(table).findByText("Test: The destination answered HTTP 500"),
    ).toBeInTheDocument();
  });

  it("is not in the nav for analysts, who still pick targets on schedules", async () => {
    const spy = await renderAt("/schedules", { mode: "login", signedIn: true, role: "analyst" });
    expect(screen.queryByRole("link", { name: "Alert targets" })).toBeNull();
    await userEvent.click(await screen.findByRole("button", { name: "New schedule" }));
    const form = screen.getByRole("form", { name: "New schedule" });
    await userEvent.selectOptions(within(form).getByLabelText("Saved search"), "failed_by_ip");
    await userEvent.click(await within(form).findByRole("checkbox", { name: "SOC Slack" }));
    await userEvent.click(within(form).getByRole("button", { name: "Create schedule" }));
    await vi.waitFor(() =>
      expect(posted(spy, (u) => u.endsWith("/api/schedules"))[0]).toMatchObject({
        target_ids: ["t1"],
      }),
    );
  });

  it("shows a schedule's delivery log with failures", async () => {
    await renderAt("/schedules", { mode: "login", signedIn: true, role: "analyst" });
    const table = await screen.findByRole("table", { name: "Schedules" });
    await userEvent.click(
      await within(table).findByRole("button", { name: "Alerts of Failed SSH daily" }),
    );
    const log = await screen.findByRole("table", { name: "Alert deliveries" });
    expect(within(log).getByText("Failed after 4 tries")).toBeInTheDocument();
    expect(within(log).getByText("The destination answered HTTP 503")).toBeInTheDocument();
  });
});
