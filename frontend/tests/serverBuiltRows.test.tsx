import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

async function renderAt(path: string) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
  return spy;
}

const called = (spy: ReturnType<typeof mockApi>, part: string) =>
  spy.mock.calls.some(([u]) => String(u).includes(part));

afterEach(() => vi.restoreAllMocks());

/** Owner, 2026-11-08: these pages ask the server for their rows by name; the SQL is built
 * there, so nothing they load goes to /api/query. */
describe("rows the server builds", () => {
  it("Sources counts and parser mix", async () => {
    const spy = await renderAt("/sources");
    await vi.waitFor(() => expect(called(spy, "/api/sources/event-counts")).toBe(true));
    expect(await screen.findByText("1,234")).toBeInTheDocument();
    expect(called(spy, "/api/query")).toBe(false);
  });

  it("Microsoft 365 Mail and Admin lists", async () => {
    for (const [path, name] of [
      ["/m365/mail", "name=mail"],
      ["/m365/admin", "name=admin"],
      ["/m365/apps", "name=consents"],
    ] as const) {
      const spy = await renderAt(path);
      await vi.waitFor(() => expect(called(spy, name)).toBe(true));
      expect(called(spy, "/api/query")).toBe(false);
    }
  });

  it("a person's sign-ins", async () => {
    const spy = await renderAt("/investigate/people#user=alice%40example.com");
    await vi.waitFor(() =>
      expect(called(spy, "/api/people/alice%40example.com/signins")).toBe(true),
    );
    expect(called(spy, "/api/query")).toBe(false);
  });
});
