import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

async function openAi(auth: MockAuth = { mode: "open" }) {
  window.history.replaceState(null, "", "/ai");
  const spy = mockApi("Codename", auth);
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
  await screen.findByRole("heading", { level: 1, name: "AI usage" });
  return spy;
}

afterEach(() => vi.restoreAllMocks());

describe("AI usage (ADR-0015)", () => {
  it("shows services with review status and lets an admin change it", async () => {
    const spy = await openAi();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByText("AI usage")).toHaveAttribute("aria-current", "page");
    expect(await screen.findByText("1 not approved in use")).toBeVisible();
    const table = screen.getByRole("region", { name: "AI services seen in network logs" });
    const row = within(table).getByText("ChatGPT").closest("tr") as HTMLElement;
    const picker = within(row).getByLabelText("Review status of ChatGPT");
    expect(picker).toHaveValue("not_approved");
    await userEvent.selectOptions(picker, "approved");
    const put = spy.mock.calls.find(
      ([u, i]) => String(u).endsWith("/api/ai/services/chatgpt/status") && i?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ status: "approved" });
  });

  it("lists agents with what changed and sets a service's allowed data", async () => {
    const spy = await openAi();
    const table = await screen.findByRole("region", { name: "AI services seen in network logs" });
    const row = within(table).getByText("ChatGPT").closest("tr") as HTMLElement;
    await userEvent.selectOptions(
      within(row).getByLabelText("Allowed data for ChatGPT"),
      "internal",
    );
    const put = spy.mock.calls.find(
      ([u, i]) => String(u).endsWith("/api/ai/services/chatgpt/data-level") && i?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ data_level: "internal" });
    await userEvent.click(screen.getByRole("tab", { name: "Agents" }));
    const agents = await screen.findByRole("table", { name: "Agents" });
    expect(within(agents).getByText("Claude Code on ws-0042")).toBeVisible();
    expect(within(agents).getByText("Changed")).toBeVisible();
    expect(within(agents).getByText("paste-share")).toBeVisible();
  });

  it("shows MCP servers and Claude usage with sensitive-data signals", async () => {
    await openAi();
    await userEvent.click(screen.getByRole("tab", { name: "MCP servers" }));
    const mcp = await screen.findByRole("region", { name: "MCP servers" });
    expect(within(mcp).getByText("paste-share")).toBeVisible();
    expect(within(mcp).getByText("inventory, telemetry")).toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: "Claude usage" }));
    const people = await screen.findByRole("region", { name: "Claude Code by person" });
    const row = within(people).getByText("alice@example.com").closest("tr") as HTMLElement;
    expect(within(row).getByText("12.50")).toBeVisible();
    expect(within(row).getByText("1 signal")).toBeVisible();
  });

  it("lists its tabs in the left nav and keeps the open one in the URL", async () => {
    await openAi();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const sections = within(nav).getByRole("list", { name: "AI usage sections" });
    expect(within(sections).getByText("Services")).toHaveAttribute("aria-current", "location");
    await userEvent.click(within(sections).getByText("MCP servers"));
    expect(window.location.hash).toBe("#mcp");
    expect(screen.getByRole("tab", { name: "MCP servers" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await userEvent.click(screen.getByRole("tab", { name: "Agents" }));
    expect(window.location.hash).toBe("#agents");
    expect(within(sections).getByText("Agents")).toHaveAttribute("aria-current", "location");
  });

  it("gives analysts read-only status and no settings", async () => {
    await openAi({ mode: "login", signedIn: true, role: "analyst" });
    expect(await screen.findByText("Not approved")).toBeVisible();
    expect(screen.queryByLabelText("Review status of ChatGPT")).toBeNull();
    expect(screen.queryByRole("tab", { name: "Review and alerts" })).toBeNull();
  });

  it("saves the AI watch", async () => {
    const spy = await openAi();
    await userEvent.click(screen.getByRole("tab", { name: "Review and alerts" }));
    const watch = await screen.findByRole("region", { name: "AI watch" });
    await userEvent.click(within(watch).getByLabelText("Watch for new AI use"));
    await userEvent.click(within(watch).getByRole("button", { name: "Save" }));
    const put = spy.mock.calls.find(
      ([u, i]) => String(u).endsWith("/api/ai/watch") && i?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toMatchObject({ enabled: true, sensitive: true });
  });
});
