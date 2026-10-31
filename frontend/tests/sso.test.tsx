import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

afterEach(() => vi.restoreAllMocks());

describe("Settings > Single sign-on (F64)", () => {
  it("shows the setup without the secret, the redirect URI, who is bound, and tests it", async () => {
    window.history.replaceState(null, "", "/sso");
    mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
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
    const status = await screen.findByRole("region", { name: "Status" });
    expect(within(status).getByText("On")).toBeVisible();
    const setup = screen.getByRole("region", { name: "Setup in use" });
    expect(within(setup).getByText("https://siem.example/api/auth/sso/callback")).toBeVisible();
    expect(within(setup).getByText("Set in the environment; never shown")).toBeVisible();
    expect(screen.getByRole("region", { name: "Bound identities" })).toHaveTextContent("jordan");
    await userEvent.click(within(status).getByRole("button", { name: "Test sign-in" }));
    expect(await within(status).findByRole("status")).toHaveTextContent("issuer matches");
  });
});
