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

  it("marks what is new and lists what is no longer seen against the previous period", async () => {
    await openAi();
    expect(await screen.findByText(/Against the previous 7 days:/)).toHaveTextContent(
      "Against the previous 7 days: 1 new, 1 no longer seen",
    );
    const table = screen.getByRole("region", { name: "AI services seen in network logs" });
    const chatgpt = within(table).getByText("ChatGPT").closest("tr") as HTMLElement;
    expect(within(chatgpt).getByText("New")).toBeVisible();
    const claude = within(table).getByText("Claude").closest("tr") as HTMLElement;
    expect(within(claude).queryByText("New")).toBeNull();
    const gone = screen.getByRole("region", { name: "No longer seen" });
    expect(within(gone).getByText("Copilot")).toBeVisible();
    expect(within(gone).getByText("Last seen 2026-10-01 09:00 UTC")).toBeVisible();
  });

  it("shows vendor ad tags apart and never as a service in use", async () => {
    await openAi();
    const table = await screen.findByRole("region", { name: "AI services seen in network logs" });
    expect(within(table).queryByText("OpenAI ad and measurement tags")).toBeNull();
    const apart = screen.getByRole("group", { name: "Not counted as AI use" });
    expect(within(apart).getByText("1 host group, 900 events")).toBeInTheDocument();
    expect(within(apart).getByText("bzr.openai.com, bzrcdn.openai.com")).toBeInTheDocument();
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

describe("A range too big for the memory share (F46)", () => {
  it("says so and shows the last 24 hours instead", async () => {
    const real = mockApi("Codename", { mode: "open" });
    const impl = real.getMockImplementation() as typeof fetch;
    real.mockRestore();
    window.history.replaceState(null, "", "/ai");
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation((url, init) => {
      const u = String(url);
      if (u.includes("/api/ai/usage")) {
        const start = new URL(u, "http://x").searchParams.get("start");
        if (start && Date.now() - Date.parse(start) > 2 * 86_400_000)
          return Promise.resolve(
            new Response(
              JSON.stringify({
                detail:
                  "The query needs more memory than this server allows. Narrow the time range or the sources, or aggregate before returning rows",
                code: "query_memory",
              }),
              { status: 400, headers: { "Content-Type": "application/json" } },
            ),
          );
      }
      return impl(url, init);
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The query needs more memory than this server allows.");
    expect(alert).toHaveTextContent("Showing the last 24 hours instead.");
    const table = await screen.findByRole("region", { name: "AI services seen in network logs" });
    expect(within(table).getByText("ChatGPT")).toBeInTheDocument();
    expect(spy.mock.calls.filter(([u]) => String(u).includes("/api/ai/usage")).length).toBe(2);
  });
});
