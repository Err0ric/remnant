import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

async function renderAt(path: string) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "analyst" });
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

describe("Your account", () => {
  it("opens from your name in the top bar and lists tokens", async () => {
    await renderAt("/search");
    await userEvent.click(await screen.findByRole("button", { name: /^jordan/ }));
    await userEvent.click(screen.getByRole("link", { name: "Your account and tokens" }));
    expect(await screen.findByRole("heading", { name: "Your account" })).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: "Tokens" });
    expect(within(table).getByText("CLI on laptop-01")).toBeInTheDocument();
  });

  it("creates a token, shows the secret once, and revokes", async () => {
    await renderAt("/me");
    const form = await screen.findByRole("form", { name: "Create token" });
    await userEvent.type(within(form).getByLabelText("Name"), "export script");
    await userEvent.click(within(form).getByRole("button", { name: "Create token" }));
    expect(await screen.findByLabelText("New token")).toHaveValue("secret-token-value");
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByLabelText("New token")).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Revoke CLI on laptop-01" }));
    await waitFor(() => expect(screen.queryByText("CLI on laptop-01")).not.toBeInTheDocument());
  });
});
