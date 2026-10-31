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

afterEach(() => vi.restoreAllMocks());

describe("Alerts (ADR-0037)", () => {
  it("is second in the nav, in the morning's order, with the open count", async () => {
    expect(AREAS.map((a) => a.label).slice(0, 2)).toEqual(["Dashboard", "Alerts"]);
    await renderAt("/alerts");
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    expect(await within(nav).findByLabelText("2 open")).toBeInTheDocument();
  });

  it("lists open alerts, counts restricted ones, and closes with a required note", async () => {
    const spy = await renderAt("/alerts");
    expect(await screen.findByText("1 restricted: it read a source you cannot see.")).toBeTruthy();
    await userEvent.click(await screen.findByRole("button", { name: /Failed logons/ }));
    expect(screen.getByText("Count 12 is above 5")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    const form = screen.getByRole("form", { name: "Close Failed logons" });
    await userEvent.click(within(form).getByLabelText("False positive (tune the rule)"));
    const submit = within(form).getByRole("button", { name: "Close alert" });
    expect(submit).toBeDisabled(); // a note is required for a false positive
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

  it("opens the alert a message links to", async () => {
    await renderAt("/alerts#item=g1");
    const here = await screen.findByRole("region", { name: "This alert" });
    expect(await within(here).findByText("Firewall reboot", { exact: false })).toBeTruthy();
    expect(within(here).getByText("Events arriving again after 25 min")).toBeInTheDocument();
    expect(within(here).getByRole("button", { name: "Reopen" })).toBeInTheDocument();
  });

  it("lets an auditor read but not close", async () => {
    await renderAt("/alerts", { mode: "login", signedIn: true, role: "auditor" });
    await userEvent.click(await screen.findByRole("button", { name: /Failed logons/ }));
    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
  });

  it("shows AI Watch severity and lets an admin approve from the item (ADR-0035)", async () => {
    const spy = await renderAt("/alerts");
    const row = await screen.findByRole("button", { name: /New AI service: DeepSeek/ });
    expect(within(row).getByText("High")).toBeInTheDocument();
    await userEvent.click(row);
    await userEvent.click(screen.getByRole("button", { name: "Not approved" }));
    await vi.waitFor(() =>
      expect(
        spy.mock.calls.some(
          ([u, init]) =>
            String(u).endsWith("/api/ai/services/deepseek/status") && init?.method === "PUT",
        ),
      ).toBe(true),
    );
  });

  it("closing an AI Watch alert can set the review status (owner, 2026-10-29)", async () => {
    const spy = await renderAt("/alerts");
    await userEvent.click(await screen.findByRole("button", { name: /New AI service: DeepSeek/ }));
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    const form = screen.getByRole("form", { name: "Close New AI service: DeepSeek" });
    const review = within(form).getByRole("group", { name: "Review status of this service" });
    expect(within(review).getByLabelText("Leave unreviewed")).toBeChecked();
    await userEvent.click(within(review).getByLabelText("Not approved"));
    await userEvent.click(within(form).getByLabelText("True positive"));
    await userEvent.click(within(form).getByRole("button", { name: "Close alert" }));
    await vi.waitFor(() => {
      const call = spy.mock.calls.find(([u]) => String(u).endsWith("/api/alerts/w1/close"));
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        reason: "true_positive",
        review_status: "not_approved",
      });
    });
  });

  it("lists AI Watch alerts still not reviewed, closed included", async () => {
    const spy = await renderAt("/alerts#review");
    expect(await screen.findByText(/still not reviewed, with their alerts open and closed/)).toBe(
      screen.getByText(/still not reviewed, with their alerts open and closed/),
    );
    expect(await screen.findByRole("button", { name: /New AI service: DeepSeek/ })).toBeVisible();
    expect(spy.mock.calls.some(([u]) => String(u).includes("unreviewed=true"))).toBe(true);
    expect(screen.queryByRole("button", { name: /stopped sending/ })).toBeNull();
  });

  it("does not offer Approve to an analyst", async () => {
    await renderAt("/alerts", { mode: "login", signedIn: true, role: "analyst" });
    await userEvent.click(await screen.findByRole("button", { name: /New AI service: DeepSeek/ }));
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("names who the alert is about and opens the rows around a fired event", async () => {
    await renderAt("/alerts");
    await userEvent.click(await screen.findByRole("button", { name: /Failed logons/ }));
    expect(await screen.findByRole("link", { name: "alice" })).toBeVisible();
    expect(screen.getByRole("link", { name: "ws-0042" })).toBeVisible();
    const rows = await screen.findByRole("table", { name: "Rows that fired" });
    await userEvent.click(within(rows).getByRole("button", { name: "Around" }));
    const box = await screen.findByRole("region", { name: "Around this event" });
    expect(await within(box).findByText("Likely cause")).toBeVisible();
  });
});
