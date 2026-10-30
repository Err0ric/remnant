import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

async function renderWith(auth: MockAuth, hash = "") {
  window.history.replaceState(null, "", `/search${hash}`);
  const fetchSpy = mockApi("Codename", auth);
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
  return fetchSpy;
}

afterEach(() => vi.restoreAllMocks());

describe("First-run setup", () => {
  it("says it creates the administrator account and signs in after setup", async () => {
    await renderWith({ mode: "setup" }, "#good-token");
    expect(
      await screen.findByText(/You are creating the administrator account for this installation/),
    ).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Password"), "a long passphrase");
    await userEvent.type(screen.getByLabelText("Confirm password"), "a long passphrase");
    await userEvent.click(screen.getByRole("button", { name: "Create administrator account" }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "Investigate" }),
    ).toBeInTheDocument();
    // The setup token is gone; Search records its own state after `#` (D90).
    expect(window.location.hash).not.toContain("good-token");
    expect(screen.getByText("jordan")).toBeInTheDocument();
  });

  it("explains where the link comes from when opened without one", async () => {
    await renderWith({ mode: "setup" });
    expect(
      await screen.findByText(/one-time setup link printed in the server log/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("checks password length and match before sending", async () => {
    const spy = await renderWith({ mode: "setup" }, "#good-token");
    await userEvent.type(await screen.findByLabelText("Password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create administrator account" }));
    expect(screen.getByRole("alert")).toHaveTextContent("at least 12 characters");
    expect(spy.mock.calls.some(([u]) => String(u).endsWith("/api/setup"))).toBe(false);
  });

  it("shows a clear message for a spent link", async () => {
    await renderWith({ mode: "setup" }, "#spent-token");
    await userEvent.type(await screen.findByLabelText("Password"), "a long passphrase");
    await userEvent.type(screen.getByLabelText("Confirm password"), "a long passphrase");
    await userEvent.click(screen.getByRole("button", { name: "Create administrator account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/invalid, expired, or already used/);
  });
});

describe("Sign in", () => {
  it("shows the error, then signs in and sends the CSRF token on writes", async () => {
    const spy = await renderWith({ mode: "login" });
    await userEvent.type(await screen.findByLabelText("Username"), "jordan");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong username or password");

    await userEvent.clear(screen.getByLabelText("Password"));
    await userEvent.type(screen.getByLabelText("Password"), "right password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "Investigate" }),
    ).toBeInTheDocument();

    await waitFor(() => {
      const call = spy.mock.calls.find(([u]) => String(u).endsWith("/api/query"));
      expect(call).toBeDefined();
      const headers = call?.[1]?.headers as Record<string, string>;
      expect(headers["X-CSRF-Token"]).toBe("csrf-1");
    });
  });

  it("signs out back to the sign-in page", async () => {
    await renderWith({ mode: "login", signedIn: true });
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("says so when the sign-out did not reach the server", async () => {
    await renderWith({ mode: "login", signedIn: true, logoutFails: true });
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/may still be active/);
  });

  it("open mode skips sign-in and shows no account menu", async () => {
    await renderWith({ mode: "open" });
    expect(
      await screen.findByRole("heading", { level: 1, name: "Investigate" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });
});

describe("Session restored on page load", () => {
  it("sends the CSRF token on the very first query, the one the page runs on open", async () => {
    const spy = await renderWith({ mode: "login", signedIn: true });
    await waitFor(() =>
      expect(spy.mock.calls.some(([u]) => String(u).endsWith("/api/query"))).toBe(true),
    );
    const [, init] = spy.mock.calls.find(([u]) => String(u).endsWith("/api/query")) ?? [];
    const headers = (init?.headers ?? {}) as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("csrf-1");
  });
});
