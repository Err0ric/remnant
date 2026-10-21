import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

async function openMcp() {
  window.history.replaceState(null, "", "/mcp-server");
  const spy = mockApi("Codename");
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
  await screen.findByRole("heading", { level: 1, name: "MCP server" });
  return spy;
}

afterEach(() => vi.restoreAllMocks());

describe("MCP server settings (ADR-0003)", () => {
  it("is off by default, saves both switches, and shows how to connect", async () => {
    const spy = await openMcp();
    const access = screen.getByRole("region", { name: "Access" });
    const on = within(access).getByRole("checkbox", { name: /Let AI assistants query logs/ });
    const local = within(access).getByRole("checkbox", { name: /run on our network/ });
    await vi.waitFor(() => expect(on).not.toBeChecked());
    expect(local).toBeDisabled();
    expect(within(access).getByText(/assumes a cloud model/)).toBeVisible();
    const save = within(access).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    await userEvent.click(on);
    await userEvent.click(local);
    await userEvent.click(save);
    expect(await within(access).findByText("Saved")).toBeVisible();
    const put = spy.mock.calls.find(
      ([u, i]) => String(u).endsWith("/api/mcp/settings") && i?.method === "PUT",
    );
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ enabled: true, endpoint_local: true });
    const connect = screen.getByRole("region", { name: "Connect a client" });
    expect(within(connect).getByLabelText("Claude Code")).toHaveTextContent(
      "claude mcp add --transport http codename",
    );
    expect(within(connect).getByLabelText(/Claude Desktop/)).toHaveTextContent('"args": [');
    const nav = screen.getByRole("navigation", { name: "Settings" });
    expect(within(nav).getByText("MCP server")).toHaveAttribute("aria-current", "page");
  });
});
