import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "./mockApi";

/** D194 (owner, 2026-11-03): "e.map is not a function" on /dashboard. Each section must
 * render, or say it did not load, whatever its response: empty, an error, or a body with
 * its optional lists missing; and opening the Dashboard after Search must not crash. */

type Shape = "empty" | "error" | "no-lists";

function strip(body: Record<string, unknown>): Record<string, unknown> {
  // Every list a section maps over, left out.
  const out = JSON.parse(JSON.stringify(body)) as Record<string, Record<string, unknown> | unknown>;
  delete out.buckets;
  for (const part of ["identity", "attacks", "detections"]) {
    const s = out[part] as Record<string, unknown> | null | undefined;
    if (!s) continue;
    for (const k of ["top_failing", "by_host", "top_sources", "by_rule", "involved"]) delete s[k];
    if (s.failed_trend) s.failed_trend = {};
    if (s.history) s.history = {};
  }
  return out as Record<string, unknown>;
}

async function openDashboard(shape: Shape, path = "/dashboard") {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
  const base = spy.getMockImplementation()!;
  spy.mockImplementation(async (input, init) => {
    const url = String(input);
    const touched = ["/api/dashboard/sections", "/api/ai/watch/summary", "/api/overview"].find(
      (p) => url.includes(p),
    );
    if (!touched) return base(input, init);
    if (shape === "error")
      return new Response(JSON.stringify({ detail: "Query failed", code: "query_failed" }), {
        status: 500,
        headers: { "content-type": "application/json" },
      });
    const res = await base(input, init);
    const body = (await res.json()) as Record<string, unknown>;
    let out: Record<string, unknown> = {};
    if (shape === "no-lists") {
      out = touched === "/api/dashboard/sections" ? strip(body) : { ...body };
      for (const k of ["cards", "chart", "top", "new", "sources", "failing"]) delete out[k];
    }
    return new Response(JSON.stringify(out), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<App initialTheme="dark" queryClient={client} />);
  return client;
}

async function settled() {
  await screen.findByRole("heading", { level: 1, name: /Dashboard/ });
  await new Promise((r) => setTimeout(r, 300));
  expect(screen.queryByText(/could not be shown/)).toBeNull();
  expect(screen.queryByText(/Something went wrong on this page/)).toBeNull();
}

afterEach(() => vi.restoreAllMocks());

describe("Dashboard sections whatever the response (D194)", () => {
  it.each<Shape>(["empty", "error", "no-lists"])("render with a %s response", async (shape) => {
    await openDashboard(shape);
    await settled();
  });

  it("opens after Search without mixing up their source lists", async () => {
    await openDashboard("empty", "/investigate/search");
    await screen.findByRole("heading", { level: 1, name: "Investigate" });
    await new Promise((r) => setTimeout(r, 300)); // Search's source filter has loaded
    window.history.pushState(null, "", "/dashboard");
    window.dispatchEvent(new Event("app:navigate"));
    await settled();
  });
});
