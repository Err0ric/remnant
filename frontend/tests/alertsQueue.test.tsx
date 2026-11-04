import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AREAS } from "@/lib/nav";
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

async function listRow(name: RegExp) {
  const list = await screen.findByRole("list", { name: "Alert list" });
  return within(list).getByRole("button", { name });
}

afterEach(() => vi.restoreAllMocks());

describe("Alerts (ADR-0037, ADR-0043)", () => {
  it("is second in the nav, in the morning's order, with the open count", async () => {
    expect(AREAS.map((a) => a.label).slice(0, 2)).toEqual(["Dashboard", "Alerts"]);
    await renderAt("/alerts");
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    expect(await within(nav).findByLabelText("2 open")).toBeInTheDocument();
  });

  it("sums up open alerts, filters the list, and opens one in the pane beside it", async () => {
    await renderAt("/alerts");
    const strip = await screen.findByRole("region", { name: "Open alerts summary" });
    expect(strip).toHaveTextContent("1 restricted (a source you cannot see)");
    expect(within(strip).getByText("New today")).toBeVisible();
    expect(strip).toHaveTextContent("New AI service: DeepSeek"); // the oldest open
    // High first, then by time: DeepSeek opens in the pane on load.
    const pane = screen.getByRole("region", { name: "This alert" });
    expect(within(pane).getByRole("heading", { name: "New AI service: DeepSeek" })).toBeVisible();
    await userEvent.click(within(strip).getByRole("button", { name: /^Detections/ }));
    const list = screen.getByRole("list", { name: "Alert list" });
    expect(within(list).queryByRole("button", { name: /DeepSeek/ })).toBeNull();
    expect(screen.getByText("1 of 2 shown")).toBeVisible();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Category" }), "");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Severity" }), "high");
    expect(within(list).queryByRole("button", { name: /Failed logons/ })).toBeNull();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Severity" }), "");
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
    await userEvent.selectOptions(within(bulk).getByRole("combobox"), "expected");
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
    expect(within(here).getByRole("button", { name: "Show events" })).toBeVisible();
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
    expect(await screen.findByText(/still not reviewed, with their alerts open and closed/)).toBe(
      screen.getByText(/still not reviewed, with their alerts open and closed/),
    );
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
    expect(await screen.findByRole("link", { name: "alice" })).toBeVisible();
    expect(screen.getByRole("link", { name: "ws-0042" })).toBeVisible();
    const rows = await screen.findByRole("table", { name: "Rows that fired" });
    await userEvent.click(within(rows).getByRole("button", { name: "Around" }));
    const box = await screen.findByRole("region", { name: "Around this event" });
    expect(await within(box).findByText("Likely cause")).toBeVisible();
  });
});
