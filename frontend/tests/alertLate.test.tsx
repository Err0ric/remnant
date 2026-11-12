import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

afterEach(() => vi.restoreAllMocks());

const START = "2026-10-09T20:01:06+00:00";
const END = "2026-10-10T08:00:00+00:00";

describe("An alert found late by a rule re-run over reparsed events (D241)", () => {
  it("shows a Late badge with the events' range on the list and on the alert", async () => {
    window.history.replaceState(null, "", "/alerts");
    const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
    const base = spy.getMockImplementation();
    spy.mockImplementation(async (input, init) => {
      const res = await base!(input, init);
      const url = String(input);
      if (!/\/api\/alerts(\/a1)?(\?|$)/.test(url)) return res;
      const body = (await res.json()) as Record<string, unknown>;
      const late = (i: Record<string, unknown>) =>
        i.item_id === "a1" ? { ...i, late: true, late_start: START, late_end: END } : i;
      const out = Array.isArray(body.items)
        ? { ...body, items: (body.items as Record<string, unknown>[]).map(late) }
        : late(body);
      return new Response(JSON.stringify(out), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);

    const list = await screen.findByRole("list", { name: "Alert list" });
    const row = await within(list).findByRole("button", { name: /Failed logons/ });
    const badge = within(row).getByText("Late");
    expect(badge).toHaveAttribute(
      "title",
      "Late detection from reparse: events 2026-10-09 20:01 to 2026-10-10 08:00 UTC",
    );
    const other = within(list).getByRole("button", { name: /DeepSeek/ });
    expect(within(other).queryByText("Late")).toBeNull();

    await userEvent.click(row);
    const pane = screen.getByRole("region", { name: "This alert" });
    await within(pane).findByRole("heading", { name: "Failed logons" });
    expect(within(pane).getByText("Late")).toBeInTheDocument();
    const found = within(pane).getByText("Late detection").nextElementSibling;
    expect(found).toHaveTextContent("Rules ran over reparsed events from");
    const times = [...(found?.querySelectorAll("time") ?? [])];
    expect(times.map((t) => t.getAttribute("datetime"))).toEqual([START, END]);
  });
});
