import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

async function renderAt(path: string, auth: MockAuth) {
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

function bodies(spy: ReturnType<typeof mockApi>, path: string): unknown[] {
  return spy.mock.calls
    .filter(([u, i]) => String(u).endsWith(path) && i?.method === "POST")
    .map(([, i]) => JSON.parse(String(i?.body)) as unknown);
}

afterEach(() => vi.restoreAllMocks());

describe("Single sign-on", () => {
  it("offers the provider first and leaves for it on click", async () => {
    const spy = await renderAt("/", { mode: "login", sso: "Microsoft" });
    const { leave } = await import("@/lib/sso");
    const assign = vi.spyOn(leave, "to").mockImplementation(() => undefined);
    await userEvent.click(await screen.findByRole("button", { name: "Continue with Microsoft" }));
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("https://login.example.test/authorize?state=s"),
    );
    expect(bodies(spy, "/api/auth/sso/start")).toEqual([{}]);
    expect(screen.getByText("Password sign-in is for administrators.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in with password" })).toBeInTheDocument();
  });

  it("explains a refused sign-in from the fixed code only", async () => {
    await renderAt("/login?sso=not_invited", { mode: "login", sso: "Microsoft" });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your Microsoft account does not have access here yet",
    );
    expect(window.location.search).toBe("");
  });

  it("shows only the password form when it is off", async () => {
    await renderAt("/", { mode: "login" });
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Continue with/ })).not.toBeInTheDocument();
  });

  it("finishes an invite link with the provider, sending the link in the body", async () => {
    const spy = await renderAt("/account#invite-token-123", { mode: "login", sso: "Microsoft" });
    const { leave } = await import("@/lib/sso");
    const assign = vi.spyOn(leave, "to").mockImplementation(() => undefined);
    expect(
      await screen.findByRole("heading", { name: "Finish setting up your account" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("New password")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Continue with Microsoft" }));
    await waitFor(() => expect(assign).toHaveBeenCalled());
    expect(bodies(spy, "/api/auth/sso/start")).toEqual([{ link_token: "invite-token-123" }]);
    const started = spy.mock.calls.find(([u]) => String(u).endsWith("/api/auth/sso/start"));
    expect(String(started?.[0])).not.toContain("invite-token-123");
  });

  it("lets an administrator set a password from the link instead", async () => {
    await renderAt("/account#invite-token-123", { mode: "login", sso: "Microsoft" });
    await userEvent.click(
      await screen.findByRole("button", { name: "Administrator? Set a password instead" }),
    );
    expect(screen.getByLabelText("New password")).toBeInTheDocument();
  });
});
