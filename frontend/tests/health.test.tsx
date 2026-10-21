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

describe("Health (ADR-0019)", () => {
  it("counts states across tabs and lists sources, agents, and watched devices", async () => {
    await renderAt("/health");
    expect(await screen.findByRole("heading", { name: "Health", level: 1 })).toBeVisible();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByText("Health")).toHaveAttribute("aria-current", "page");
    const sources = await screen.findByRole("table", { name: "Sources" });
    expect(within(sources).getByText("linux_sshd")).toBeVisible();
    const unhealthy = screen.getByRole("button", { name: /Unhealthy/ });
    expect(await within(unhealthy).findByText("1")).toBeVisible(); // the silent sensor

    await userEvent.click(screen.getByRole("tab", { name: /Agents/ }));
    const agents = await screen.findByRole("table", { name: "Agents" });
    expect(within(agents).getByText("ws-0042")).toBeVisible();
    expect(within(agents).getByText("Last reported 2 d ago")).toBeVisible();

    await userEvent.click(screen.getByRole("tab", { name: /Watched devices/ }));
    const devices = await screen.findByRole("table", { name: "Watched devices" });
    expect(within(devices).getByText("Site B network sensor")).toBeVisible();
    expect(within(devices).getByText("Silent 47 min (allowed 15 min)")).toBeVisible();
  });

  it("lets administrators watch a device", async () => {
    const spy = await renderAt("/health");
    await userEvent.click(await screen.findByRole("tab", { name: /Watched devices/ }));
    await userEvent.click(screen.getByRole("button", { name: "Watch a device" }));
    const form = screen.getByRole("form", { name: "Watch a device" });
    await userEvent.type(within(form).getByLabelText("Name"), "Core firewall");
    await userEvent.type(within(form).getByLabelText("IP address or host name"), "FW-CORE");
    await userEvent.click(within(form).getByRole("button", { name: "Watch device" }));
    expect(await screen.findByText("Core firewall")).toBeVisible();
    const call = spy.mock.calls.find(
      ([u, i]) => String(u).endsWith("/api/health-checks/devices") && i?.method === "POST",
    );
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ match: "FW-CORE", silence_s: 900 });
  });

  it("does not offer device changes to analysts", async () => {
    await renderAt("/health", { mode: "login", signedIn: true, role: "analyst" });
    await userEvent.click(await screen.findByRole("tab", { name: /Watched devices/ }));
    await screen.findByRole("table", { name: "Watched devices" });
    expect(screen.queryByRole("button", { name: "Watch a device" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Stop watching/ })).toBeNull();
  });
});
