import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, type MockAuth } from "./mockApi";

async function openIdentities(auth: MockAuth = { mode: "open" }) {
  window.history.replaceState(null, "", "/identities");
  const spy = mockApi("Codename", auth);
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
  return spy;
}

function puts(spy: ReturnType<typeof mockApi>, path: string) {
  return spy.mock.calls
    .filter(([u, i]) => String(u).endsWith(path) && i?.method === "PUT")
    .map(([, i]) => JSON.parse(String(i?.body)) as unknown);
}

afterEach(() => vi.restoreAllMocks());

describe("Identities (ADR-0018)", () => {
  it("lives in Settings and accepts a domain suggestion with its evidence", async () => {
    const spy = await openIdentities();
    await screen.findByRole("heading", { level: 1, name: "Identities" });
    const sub = screen.getByRole("navigation", { name: "Settings" });
    expect(within(sub).getByText("Identities")).toHaveAttribute("aria-current", "page");
    const sug = screen.getByRole("region", { name: "Suggestions" });
    expect(
      await within(sug).findByText(/2 of 3 addresses also appear as bare names/),
    ).toBeVisible();
    await userEvent.click(
      within(sug).getAllByRole("button", { name: "Add domain" })[0] as HTMLElement,
    );
    expect(puts(spy, "/api/identities/domains")).toEqual([{ domains: ["example.com"] }]);
  });

  it("accepts a same-machine suggestion and adds and removes aliases", async () => {
    const spy = await openIdentities();
    const sug = await screen.findByRole("region", { name: "Suggestions" });
    expect(await within(sug).findByText("ws-0311")).toBeVisible();
    await userEvent.click(within(sug).getByRole("button", { name: "Accept" }));
    const form = screen.getByRole("form", { name: "Add an alias" });
    await userEvent.type(within(form).getByLabelText("Name as logged"), "jdoe");
    await userEvent.type(within(form).getByLabelText("Person"), "jane.doe@example.com");
    await userEvent.click(within(form).getByRole("button", { name: "Add alias" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove alias jsmith" }));
    expect(puts(spy, "/api/identities/aliases")).toEqual([
      { alias: "carol", person: "carol@example.com" },
      { alias: "jdoe", person: "jane.doe@example.com" },
      { alias: "jsmith", person: null },
    ]);
  });

  it("is hidden from analysts", async () => {
    await openIdentities({ mode: "login", signedIn: true, role: "analyst" });
    await screen.findByRole("navigation", { name: "Primary" });
    expect(screen.queryByRole("heading", { level: 1, name: "Identities" })).toBeNull();
  });
});
