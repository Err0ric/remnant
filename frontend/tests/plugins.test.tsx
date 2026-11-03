import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

afterEach(() => vi.restoreAllMocks());

async function openPlugins() {
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
  await screen.findByRole("region", { name: "Claude Code for Windows" });
  return spy;
}

function pluginBodies(spy: ReturnType<typeof mockApi>) {
  return spy.mock.calls
    .filter(([u]) => String(u).endsWith("/api/sources/claude/claude-plugin"))
    .map(([, i]) => JSON.parse(String(i?.body)) as Record<string, unknown>);
}

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

  it("falls back to a new token when the picked one is revoked (owner, 2026-11-02)", async () => {
    const spy = await openPlugins();
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: /^Deployment token/ }),
      "t1",
    );
    const tokens = screen.getByRole("region", { name: "Deployment tokens" });
    await userEvent.click(within(tokens).getByRole("button", { name: "Revoke" }));
    await userEvent.click(within(tokens).getByRole("button", { name: "Revoke" }));
    await screen.findByText(/^Revoked/);
    // No stale selection: the picker shows New token, and a download mints a fresh one.
    expect(screen.getByRole("combobox", { name: /^Deployment token/ })).toHaveValue("__new__");
    expect(screen.getByLabelText("Token name")).toBeVisible();
    const windows = screen.getByRole("region", { name: "Claude Code for Windows" });
    await userEvent.click(within(windows).getByRole("button", { name: "Download plugin" }));
    await waitFor(() => expect(pluginBodies(spy)).toHaveLength(1));
    expect(pluginBodies(spy)[0]).not.toHaveProperty("token_id");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("warns that everyone sends when Pilot users is empty", async () => {
    await openPlugins();
    expect(screen.getByRole("note")).toHaveTextContent(
      "Everyone who installs this plugin will send records.",
    );
    await userEvent.type(screen.getByRole("textbox", { name: /^Pilot users/ }), "dana@example.com");
    expect(screen.queryByRole("note")).toBeNull();
    expect(screen.getByText("Only this person sends.")).toBeVisible();
  });

  it("leaves the self-signed certificate out behind a reverse proxy, and says why", async () => {
    const spy = await openPlugins();
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const box = screen.getByRole("checkbox", { name: /self-signed certificate/ });
    expect(box).not.toBeChecked();
    expect(screen.getByText(/through a reverse proxy/)).toBeVisible();
    const windows = screen.getByRole("region", { name: "Claude Code for Windows" });
    await userEvent.click(within(windows).getByRole("button", { name: "Download plugin" }));
    await waitFor(() => expect(pluginBodies(spy)).toHaveLength(1));
    expect(pluginBodies(spy)[0]).toMatchObject({ trust_server_certificate: false });
  });

  it("sends a test record per deployment and shows the HTTP result (owner 2026-11-02)", async () => {
    const spy = await openPlugins();
    const tokens = screen.getByRole("region", { name: "Deployment tokens" });
    await userEvent.click(within(tokens).getByRole("button", { name: /^Send a test record with/ }));
    expect(await within(tokens).findByRole("status")).toHaveTextContent(
      "HTTP 200. Accepted: the receiver took the record with this token.",
    );
    expect(
      spy.mock.calls.some(
        ([u, i]) => String(u).endsWith("/otlp-tokens/t1/test") && i?.method === "POST",
      ),
    ).toBe(true);
  });
});
