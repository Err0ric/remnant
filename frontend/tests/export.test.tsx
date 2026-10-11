import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

afterEach(() => vi.restoreAllMocks());

it("exports through the server with exactly the request that produced the table", async () => {
  window.history.replaceState(null, "", "/search");
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "analyst" });
  Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(<App initialTheme="dark" queryClient={client} />);
  const button = await screen.findByRole("button", { name: "Export CSV" });
  await vi.waitFor(() => expect(button).toBeEnabled());
  await userEvent.click(button);
  await vi.waitFor(() => expect(click).toHaveBeenCalled());
  const bodies = (suffix: string) =>
    spy.mock.calls
      .filter(([u, i]) => String(u).endsWith(suffix) && i?.method === "POST")
      .map(([, i]) => String(i?.body));
  const runs = bodies("/api/query").filter((b) => !b.includes("GROUP BY source_id"));
  expect(bodies("/api/query/export")).toEqual([runs[runs.length - 1]]);
});
