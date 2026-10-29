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

afterEach(() => vi.restoreAllMocks());

describe("AI Watch on the Dashboard (ADR-0035 Part 2)", () => {
  it("shows five cards against the previous period, the 30-day chart, and top services", async () => {
    const spy = await renderAt("/dashboard");
    const watch = await screen.findByRole("region", { name: "AI Watch" });
    expect(within(watch).getByText("Unapproved AI services")).toBeVisible();
    expect(within(watch).getByRole("button", { name: "2" })).toBeVisible();
    expect(within(watch).getAllByText("+1 vs previous 7 days")).toHaveLength(2);
    expect(within(watch).getByText("same as previous 7 days")).toBeVisible();
    // People and devices are never one number: devices without a person are their own line.
    expect(
      within(watch).getByRole("button", { name: "2 more devices not matched to a person" }),
    ).toBeVisible();
    // A card without its source takes no card (F62): one muted line with the setup link.
    expect(within(watch).queryByText("App consent grants")).toBeNull();
    expect(within(watch).getByText(/^Not set up:/)).toHaveTextContent(
      "app consent grants (needs a Microsoft 365 source)",
    );
    // Capitals stay on product words: "MCP servers", "AI".
    expect(within(watch).getByText(/^Not set up:/)).not.toHaveTextContent(/mcp servers|to ai\b/);
    expect(within(watch).getByRole("button", { name: "Add a source" })).toBeVisible();
    expect(within(watch).getByText("Restricted")).toBeVisible();
    // New in 24 hours sits under the cards, from first seen.
    expect(within(watch).getByRole("link", { name: "DeepSeek (AI service)" })).toHaveAttribute(
      "href",
      "/alerts#item=w1",
    );
    expect(
      within(watch).getByRole("img", { name: /^AI use per day over 30 days by review status:/ }),
    ).toBeVisible();
    const top = within(watch).getByRole("table", { name: "Top AI services" });
    expect(within(top).getByRole("link", { name: "DeepSeek" })).toBeVisible();
    expect(within(top).getByText("Not approved")).toBeVisible();
    await userEvent.click(within(watch).getByRole("button", { name: "30 days" }));
    await vi.waitFor(() =>
      expect(
        spy.mock.calls.some(([u]) => String(u).endsWith("/api/ai/watch/summary?days=30")),
      ).toBe(true),
    );
  });
});

describe("A dashboard section that fails to load (F63)", () => {
  it("stays on the page with a plain error and Retry", async () => {
    const real = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
    const impl = real.getMockImplementation() as typeof fetch;
    real.mockRestore();
    window.history.replaceState(null, "", "/dashboard");
    let fail = true;
    vi.spyOn(globalThis, "fetch").mockImplementation((url, init) => {
      if (fail && String(url).includes("/api/ai/watch/summary"))
        return Promise.resolve(
          new Response(
            JSON.stringify({
              detail: "The query needs more memory than this server allows.",
              code: "query_memory",
            }),
            {
              status: 503,
              headers: { "Content-Type": "application/json", "X-Request-ID": "a1b2c3d4e5f6" },
            },
          ),
        );
      return impl(url, init);
    });
    vi.resetModules();
    const { loadBranding } = await import("@/lib/branding");
    await loadBranding();
    const { App } = await import("@/app/App");
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<App initialTheme="dark" queryClient={client} />);
    const watch = await screen.findByRole("region", { name: "AI Watch" });
    const alert = await within(watch).findByRole("alert");
    expect(alert).toHaveTextContent(
      "AI Watch did not load: the query needed more memory than this server allows.",
    );
    expect(alert).toHaveTextContent("Request a1b2c3d4e5f6");
    // The server is not "unreachable": a limit with a code is an answer.
    expect(screen.queryByText(/cannot reach the server/i)).toBeNull();
    fail = false;
    await userEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await within(watch).findByText("Unapproved AI services")).toBeVisible();
    expect(within(watch).queryByRole("alert")).toBeNull();
  });
});

describe("AI Watch wording and chart (owner nits, 2026-10-29)", () => {
  it("keeps capitals inside the Not set up sentence", async () => {
    const { midSentence } = await import("@/features/dashboard/AiWatch");
    expect(midSentence("New agents and MCP servers")).toBe("new agents and MCP servers");
    expect(midSentence("Sensitive data to AI")).toBe("sensitive data to AI");
    expect(midSentence("MCP servers")).toBe("MCP servers");
    expect(midSentence("App consent grants")).toBe("app consent grants");
  });

  it("covers only the days that exist until there are 30", async () => {
    const { Chart } = await import("@/features/dashboard/AiWatch");
    const chart = Array.from({ length: 30 }, (_, i) => ({
      day: new Date(Date.UTC(2026, 8, 30 + i)).toISOString().slice(0, 10),
      approved: i >= 22 ? 3 : 0, // 8 days of data: Oct 22 to Oct 29
      unreviewed: 0,
      not_approved: 0,
    }));
    render(<Chart chart={chart} />);
    expect(screen.getByText(/^AI use since Oct 22/)).toBeVisible();
    expect(screen.getByRole("img")).toHaveAttribute(
      "aria-label",
      expect.stringContaining("over 8 days"),
    );
  });
});
