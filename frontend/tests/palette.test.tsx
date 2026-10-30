import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

async function renderAt(path: string, auth: MockAuth = { mode: "open" }) {
  window.history.replaceState(null, "", path);
  try {
    window.localStorage.clear();
  } catch {
    // jsdom always has storage; kept for parity with the app code
  }
  const spy = mockApi("Codename", auth);
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
  await screen.findByRole("navigation", { name: "Primary" });
  return spy;
}

async function openWithKeys() {
  await userEvent.keyboard("{Control>}k{/Control}");
  return screen.findByRole("dialog", { name: "Command palette" });
}

afterEach(() => vi.restoreAllMocks());

describe("Command palette", () => {
  it("opens on Ctrl+K and from the top bar, and closes on Escape", async () => {
    await renderAt("/overview");
    const dialog = await openWithKeys();
    expect(within(dialog).getByRole("combobox")).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open the command palette" }));
    expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
  });

  it("finds pages by flavor names and goes there with Enter", async () => {
    await renderAt("/overview");
    const dialog = await openWithKeys();
    await userEvent.type(within(dialog).getByRole("combobox"), "grimoire");
    const options = within(dialog).getAllByRole("option");
    expect(options[0]).toHaveTextContent("Saved searches");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(window.location.pathname).toBe("/investigate/saved"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("offers only the pages a role can open", async () => {
    await renderAt("/overview", { mode: "login", signedIn: true, role: "analyst" });
    const dialog = await openWithKeys();
    await userEvent.type(within(dialog).getByRole("combobox"), "users");
    expect(within(dialog).queryByText("Users and access")).not.toBeInTheDocument();
    await userEvent.clear(within(dialog).getByRole("combobox"));
    await userEvent.type(within(dialog).getByRole("combobox"), "audit");
    expect(within(dialog).queryByText("Audit log")).not.toBeInTheDocument();
  });

  it("opens a saved search ready to run", async () => {
    await renderAt("/overview");
    const dialog = await openWithKeys();
    await userEvent.type(within(dialog).getByRole("combobox"), "failed ssh by");
    await userEvent.click(await within(dialog).findByText("Failed SSH by source"));
    await waitFor(() => expect(window.location.pathname).toBe("/investigate/saved"));
    expect(
      await screen.findByRole("region", { name: "Run Failed SSH by source" }),
    ).toBeInTheDocument();
  });

  it("searches one source, filtered on the server request", async () => {
    const spy = await renderAt("/overview");
    const dialog = await openWithKeys();
    await userEvent.type(within(dialog).getByRole("combobox"), "linux_sshd");
    await userEvent.click(await within(dialog).findByText("linux_sshd"));
    await waitFor(() => expect(window.location.pathname).toBe("/investigate/search"));
    await waitFor(() => {
      const bodies = spy.mock.calls
        .filter(([u, i]) => String(u).endsWith("/api/query") && i?.method === "POST")
        .map(([, i]) => JSON.parse(String(i?.body)) as { sources?: string[] });
      expect(bodies.some((b) => b.sources?.[0] === "linux_sshd")).toBe(true);
    });
  });

  it("switches the AI provider Ask uses", async () => {
    await renderAt("/ask");
    const dialog = await openWithKeys();
    await userEvent.type(within(dialog).getByRole("combobox"), "use cloud");
    await userEvent.click(await within(dialog).findByText("Use Cloud for Ask"));
    await waitFor(() => expect(screen.getByLabelText("Model")).toHaveValue("p2"));
  });

  it("runs the current search", async () => {
    const spy = await renderAt("/search");
    const queries = () =>
      spy.mock.calls.filter(
        ([u, i]) =>
          (String(u).endsWith("/api/query") || String(u).endsWith("/api/search/compile")) &&
          i?.method === "POST",
      ).length;
    await waitFor(() => expect(queries()).toBeGreaterThan(0));
    const before = queries();
    const dialog = await openWithKeys();
    await userEvent.type(within(dialog).getByRole("combobox"), "run the current");
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(queries()).toBeGreaterThan(before));
  });
});
