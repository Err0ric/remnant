import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";
import { RiskTable } from "@/features/investigate/RiskTable";
import type { EntityRisk } from "@/lib/api";

afterEach(() => vi.restoreAllMocks());

const ROW: EntityRisk = {
  kind: "user",
  value: "alice@example.com",
  score: 3,
  critical: 0,
  high: 0,
  medium: 0,
  low: 0,
  flagged_runs: 0,
  events: 12,
  rules: [],
  search_sql: "SELECT 1",
  failed_signins: 3,
  ai_flags: [],
  alerts: 0,
  parts: { failed_signins: 3 },
};

function table(kind: "user" | "host", hidden: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RiskTable
        kind={kind}
        label={kind === "user" ? "User" : "Host"}
        rows={[{ ...ROW, kind }]}
        onPick={() => {}}
        aiPeopleHidden={hidden}
      />
    </QueryClientProvider>,
  );
  return within(screen.getByRole("table"));
}

describe("People & devices without View people in AI usage (D242)", () => {
  it("says a person's AI watch flags are hidden instead of showing 0", () => {
    const cell = table("user", true).getByText("Hidden");
    expect(cell).toHaveAttribute("title", "Needs View people in AI usage");
  });

  it("keeps the count for a viewer with the permission", () => {
    expect(table("user", false).queryByText("Hidden")).toBeNull();
  });

  it("keeps the count for machines", () => {
    expect(table("host", true).queryByText("Hidden")).toBeNull();
  });

  it("the page passes the server's answer on to the table", async () => {
    window.history.replaceState(null, "", "/investigations");
    const spy = mockApi("Codename", { mode: "open" });
    const base = spy.getMockImplementation()!;
    spy.mockImplementation(async (input, init) => {
      const res = await base(input, init);
      if (!String(input).includes("/api/entities/risk")) return res;
      const body = (await res.json()) as Record<string, unknown>;
      return new Response(JSON.stringify({ ...body, ai_people_hidden: true }), {
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
    const users = await screen.findByRole("table", { name: "User" });
    expect(within(users).getAllByText("Hidden").length).toBeGreaterThan(0);
  });
});
