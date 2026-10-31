import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

afterEach(() => vi.restoreAllMocks());

describe("Settings > Claude plugins (D127)", () => {
  it("offers each platform, names the deployment token, and revokes one alone", async () => {
    window.history.replaceState(null, "", "/plugins");
    const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
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
    const windows = await screen.findByRole("region", { name: "Claude Code for Windows" });
    expect(within(windows).getByText("ab".repeat(32))).toBeVisible();
    const tokens = screen.getByRole("region", { name: "Deployment tokens" });
    expect(within(tokens).getByText("rmt_ab12…")).toBeVisible();
    await userEvent.type(screen.getByLabelText("Token name"), "all windows");
    await userEvent.click(within(windows).getByRole("button", { name: "Download plugin" }));
    await waitFor(() => {
      const bodies = spy.mock.calls
        .filter(([u]) => String(u).endsWith("/api/sources/claude/claude-plugin"))
        .map(([, i]) => JSON.parse(String(i?.body)) as { token_name?: string; platform: string });
      expect(bodies).toContainEqual(
        expect.objectContaining({ token_name: "all windows", platform: "windows" }),
      );
    });
    await userEvent.click(within(tokens).getByRole("button", { name: "Revoke" }));
    expect(within(tokens).getByText("3 devices stop sending.")).toBeVisible();
    await userEvent.click(within(tokens).getByRole("button", { name: "Revoke" }));
    await waitFor(() =>
      expect(
        spy.mock.calls.some(
          ([u, i]) => String(u).endsWith("/otlp-tokens/t1") && i?.method === "DELETE",
        ),
      ).toBe(true),
    );
  });
});
