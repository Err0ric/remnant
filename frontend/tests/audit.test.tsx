import { QueryClient } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
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
    expect(within(table).getByText("Ran a search")).toBeVisible();
    expect(within(table).getByText("none")).toBeVisible(); // a failed login has no user
    await userEvent.click(within(table).getByRole("button", { name: "ana" }));
    expect(await screen.findByText("User: ana")).toBeVisible();
    await vi.waitFor(() => expect(urls(spy, "user_id=u2").length).toBeGreaterThan(0));
    await userEvent.click(screen.getByRole("button", { name: /Details of Ran a search/ }));
    expect(screen.getByText(/"sql": "SELECT 1"/)).toBeVisible();
    const nav = screen.getByRole("navigation", { name: "Settings" });
    expect(within(nav).getByText("Audit log")).toHaveAttribute("aria-current", "page");
  });

  it("shows AI calls without bodies and exports the current log", async () => {
    const spy = await renderAt("/audit", auditor);
    await screen.findByRole("table", { name: "Activity" });
    await userEvent.click(screen.getByRole("tab", { name: "AI calls" }));
    const table = await screen.findByRole("table", { name: "AI calls" });
    expect(within(table).getByText("qwen3.5:9b")).toBeVisible();
    expect(within(table).getByText("Answered")).toBeVisible();
    await userEvent.click(within(table).getAllByRole("button", { expanded: false })[0]!);
    expect(within(table).getByText("Ollama on the LAN (p1)")).toBeVisible();
    expect(within(table).getByText("d".repeat(64))).toBeVisible();
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));
    await vi.waitFor(() => expect(urls(spy, "/api/audit/llm-calls/export").length).toBe(1));
  });

  it("shows integrity findings to auditors and lets admins verify and choose targets", async () => {
    await renderAt("/audit#integrity", auditor);
    expect(await screen.findByText("Failed")).toBeVisible();
    const findings = screen.getByRole("region", { name: "Findings" });
    expect(within(findings).getByText("Changed")).toBeVisible();
    expect(within(findings).getByText(/part-0001.parquet/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Verify now" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Integrity alerts" })).toBeNull();
    cleanup();

    const spy = await renderAt("/audit#integrity", {
      mode: "login",
      signedIn: true,
      role: "admin",
    });
    await userEvent.click(await screen.findByRole("button", { name: "Verify now" }));
    await vi.waitFor(() => expect(urls(spy, "/api/integrity/verify").length).toBe(1));
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Send a daily seal to these targets" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(urls(spy, "/api/integrity/settings").length).toBe(1));
  });

  it("is not offered to analysts", async () => {
    await renderAt("/audit", { mode: "login", signedIn: true, role: "analyst" });
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    expect(within(nav).queryByText("Audit log")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Audit log" })).toBeNull();
  });
});
