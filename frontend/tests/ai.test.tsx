import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

/** A rail area, then one of its tabs in the page header (ADR-0038). */
async function goTo(area: string, tab?: string) {
  const nav = screen.getByRole("navigation", { name: "Primary" });
  await userEvent.click(within(nav).getByRole("link", { name: area }));
  if (tab) {
    const tabs = await screen.findByRole("navigation", { name: `${area} tabs` });
    await userEvent.click(within(tabs).getByRole("link", { name: tab }));
  }
}

async function openAi(auth: MockAuth = { mode: "open" }) {
  window.history.replaceState(null, "", "/ai");
  return openAiAt(auth);
}

async function openAiAt(auth: MockAuth = { mode: "open" }) {
  const spy = mockApi("Codename", auth);
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
  await screen.findByRole("heading", { level: 1 });
  return spy;
}

afterEach(() => vi.restoreAllMocks());

describe("AI usage (ADR-0015)", () => {
  it("shows services with review status and lets an admin change it", async () => {
    const spy = await openAi();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: "AI usage" })).toHaveAttribute(
      "aria-current",
      "true",
    );
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
    await goTo("Agents");
    const agents = await screen.findByRole("table", { name: "Agents" });
    expect(within(agents).getByText("Claude Code on ws-0042")).toBeVisible();
    expect(within(agents).getByText("Changed")).toBeVisible();
    expect(within(agents).getByText("paste-share")).toBeVisible();
  });

  it("shows MCP servers and Claude usage with sensitive-data signals", async () => {
    await openAi();
    await goTo("Agents", "MCP servers");
    const mcp = await screen.findByRole("region", { name: "MCP servers" });
    expect(within(mcp).getByText("paste-share")).toBeVisible();
    expect(within(mcp).getByText("inventory, telemetry")).toBeVisible();
    await goTo("AI usage", "People");
    const people = await screen.findByRole("region", { name: "Claude Code by person" });
    const row = within(people).getByText("alice@example.com").closest("tr") as HTMLElement;
    expect(within(row).getByText("12.50")).toBeVisible();
    expect(within(row).getByText("1 signal")).toBeVisible();
  });

  it("shows its tabs in the page header and keeps the open one in the path (ADR-0038)", async () => {
    await openAi();
    const tabs = screen.getByRole("navigation", { name: "AI usage tabs" });
    expect(within(tabs).getByRole("link", { name: "Services" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await userEvent.click(within(tabs).getByRole("link", { name: "People" }));
    expect(window.location.pathname).toBe("/ai/people");
    await goTo("Agents", "MCP servers");
    expect(window.location.pathname).toBe("/agents/mcp");
  });

  it("opens links from before the areas at their new address", async () => {
    window.history.replaceState(null, "", "/ai#mcp");
    await openAiAt();
    await screen.findByRole("region", { name: "MCP servers" });
    expect(window.location.pathname + window.location.hash).toBe("/agents/mcp");
  });

  it("gives analysts read-only status and no settings", async () => {
    await openAi({ mode: "login", signedIn: true, role: "analyst" });
    expect(await screen.findByText("Not approved")).toBeVisible();
    expect(screen.queryByLabelText("Review status of ChatGPT")).toBeNull();
    expect(screen.queryByRole("link", { name: "Review" })).toBeNull();
  });

  it("saves the AI watch", async () => {
    const spy = await openAi();
    await goTo("AI usage", "Review");
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
              { status: 503, headers: { "Content-Type": "application/json" } },
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

describe("Agent sessions from the hooks plugin (ADR-0026)", () => {
  it("lists sessions and opens one in order", async () => {
    window.history.replaceState(null, "", "/ai#agents");
    mockApi("Codename", { mode: "open" });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    render(
      <App
        initialTheme="dark"
        queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      />,
    );
    const card = await screen.findByRole("region", { name: "Agent sessions" });
    await userEvent.click(await within(card).findByRole("button", { name: "dana@example.com" }));
    const steps = await within(card).findByRole("list", { name: "Session timeline" });
    const items = within(steps).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[2]).toHaveTextContent("Calls Read /home/dana/app/auth.py");
    expect(items[3]).toHaveTextContent("github create_issue");
    expect(items[1]).toHaveTextContent("42 chars");
  });
});
