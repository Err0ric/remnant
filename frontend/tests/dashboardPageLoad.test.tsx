import { QueryClient } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "./mockApi";

/** Handoff item 3: every request of one Dashboard visit carries the same page-load id and
 * the list of every part the page requests, so the server writes the visit's audit row on
 * the first request; a page without it sends none. */

function headerOf(init: RequestInit | undefined, name = "X-Page-Load"): string | undefined {
  return (init?.headers as Record<string, string> | undefined)?.[name];
}

function calls(prefix: string, name = "X-Page-Load"): (string | undefined)[] {
  return vi
    .mocked(globalThis.fetch)
    .mock.calls.filter((c) => String(c[0]).includes(prefix))
    .map((c) => headerOf(c[1], name));
}

/** The section parts the page actually requested, from the request URLs. */
function partsFetched(): Set<string> {
  const out = new Set<string>();
  for (const c of vi.mocked(globalThis.fetch).mock.calls) {
    const url = new URL(String(c[0]), "http://localhost");
    if (url.pathname === "/api/dashboard/sections") out.add(url.searchParams.get("part") ?? "");
    if (url.pathname === "/api/overview") out.add("overview");
  }
  return out;
}

async function open(path: string) {
  window.history.replaceState(null, "", path);
  mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
  return client;
}

afterEach(() => vi.restoreAllMocks());

describe("one page-load id per Dashboard visit", () => {
  it("sends the same id with the sections and the Overview", async () => {
    await open("/dashboard");
    await screen.findByRole("heading", { level: 1, name: /Dashboard/ });
    await vi.waitFor(() => {
      expect(calls("/api/dashboard/sections").length).toBeGreaterThanOrEqual(3);
      expect(calls("/api/overview").length).toBeGreaterThanOrEqual(1);
    });
    const ids = new Set([...calls("/api/dashboard/sections"), ...calls("/api/overview")]);
    expect(ids.size).toBe(1);
    expect([...ids][0]).toMatch(/^[A-Za-z0-9-]{8,64}$/);
  });

  it("keeps the same id for refetches while the page stays open", async () => {
    const client = await open("/dashboard");
    await screen.findByRole("heading", { level: 1, name: /Dashboard/ });
    await vi.waitFor(() => {
      expect(calls("/api/dashboard/sections").length).toBeGreaterThanOrEqual(3);
      expect(calls("/api/overview").length).toBeGreaterThanOrEqual(1);
    });
    const sections = calls("/api/dashboard/sections").length;
    const overview = calls("/api/overview").length;
    // What the page's 60 s and 300 s timers do: refetch every active query.
    await act(() => client.refetchQueries({ type: "active" }));
    await vi.waitFor(() => {
      expect(calls("/api/dashboard/sections").length).toBeGreaterThan(sections);
      expect(calls("/api/overview").length).toBeGreaterThan(overview);
    });
    const ids = new Set([...calls("/api/dashboard/sections"), ...calls("/api/overview")]);
    expect(ids.size).toBe(1);
  });

  it("declares every part the page fetches, with the page window", async () => {
    await open("/dashboard");
    await screen.findByRole("heading", { level: 1, name: /Dashboard/ });
    await vi.waitFor(() => {
      expect(calls("/api/dashboard/sections").length).toBeGreaterThanOrEqual(3);
      expect(calls("/api/overview").length).toBeGreaterThanOrEqual(1);
    });
    const lists = new Set([
      ...calls("/api/dashboard/sections", "X-Page-Load-Parts"),
      ...calls("/api/overview", "X-Page-Load-Parts"),
    ]);
    expect(lists.size).toBe(1);
    const declared = new Set(String([...lists][0]).split(","));
    expect(declared).toEqual(
      new Set(["identity", "attacks", "detections", "overview", "ai_watch"]),
    );
    for (const part of partsFetched()) expect(declared).toContain(part);
    expect(new Set(calls("/api/dashboard/sections", "X-Page-Load-Window"))).toEqual(
      new Set(["7d"]),
    );
  });

  it("sends none after leaving the Dashboard", async () => {
    await open("/dashboard");
    await screen.findByRole("heading", { level: 1, name: /Dashboard/ });
    const fetches = vi.mocked(globalThis.fetch).mock.calls;
    let before = 0;
    act(() => {
      before = fetches.length;
      window.history.pushState(null, "", "/investigate/logs");
      window.dispatchEvent(new Event("app:navigate"));
    });
    await screen.findByRole("heading", { level: 1, name: "Logs" });
    await vi.waitFor(() => expect(fetches.length).toBeGreaterThan(before));
    // Requests the new page made, after the Dashboard's own cleanup ran.
    const after = fetches.slice(before).filter((c) => !String(c[0]).includes("/api/dashboard"));
    for (const c of after) expect(headerOf(c[1])).toBeUndefined();
  });
});
