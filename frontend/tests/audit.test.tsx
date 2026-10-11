import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

async function renderAt(path: string, auth: MockAuth) {
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

function urls(spy: ReturnType<typeof mockApi>, part: string): string[] {
  return spy.mock.calls.map(([u]) => String(u)).filter((u) => u.includes(part));
}

afterEach(() => vi.restoreAllMocks());

describe("Audit log", () => {
  const auditor: MockAuth = { mode: "login", signedIn: true, role: "auditor" };

  it("lists activity for auditors, filters by a clicked user, and shows detail as text", async () => {
    const spy = await renderAt("/audit", auditor);
    const table = await screen.findByRole("table", { name: "Activity" });
    expect(within(table).getByText("query.run")).toBeVisible();
    expect(within(table).getByText("none")).toBeVisible(); // a failed login has no user
    await userEvent.click(within(table).getByRole("button", { name: "ana" }));
    expect(await screen.findByText("User: ana")).toBeVisible();
    await vi.waitFor(() => expect(urls(spy, "user_id=u2").length).toBeGreaterThan(0));
    await userEvent.click(screen.getByRole("button", { name: /Details of query.run/ }));
    expect(screen.getByText(/"sql": "SELECT 1"/)).toBeVisible();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByText("Audit log")).toHaveAttribute("aria-current", "page");
  });

  it("shows AI calls without bodies and exports the current log", async () => {
    const spy = await renderAt("/audit", auditor);
    await screen.findByRole("table", { name: "Activity" });
    await userEvent.click(screen.getByRole("tab", { name: "AI calls" }));
    const table = await screen.findByRole("table", { name: "AI calls" });
    expect(within(table).getByText("qwen3.5:9b")).toBeVisible();
    expect(within(table).getByText("Answered")).toBeVisible();
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await vi.waitFor(() => expect(urls(spy, "/api/audit/llm-calls/export").length).toBe(1));
  });

  it("is not offered to analysts", async () => {
    await renderAt("/audit", { mode: "login", signedIn: true, role: "analyst" });
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    expect(within(nav).queryByText("Audit log")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Audit log" })).toBeNull();
  });
});
