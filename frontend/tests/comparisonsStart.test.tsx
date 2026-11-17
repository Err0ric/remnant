import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { compareLine } from "@/features/dashboard/History";
import { mockApi } from "./mockApi";

// Fix list item 8: every page that compares says when comparisons start from the server's
// `starts`, never from date math of its own.
const STARTS = "2026-12-27T12:00:00Z";
const NOT_COMPARED = { compared: false, since: "2026-10-31T17:00:00Z", starts: STARTS };

/** Opens `path` with the given answers changed to "not compared yet". */
async function openWith(
  path: string,
  patch: (url: string, body: Record<string, unknown> | null) => unknown,
) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "open" });
  const real = spy.getMockImplementation() as typeof fetch;
  spy.mockImplementation(async (url, init) => {
    const res = await real(url, init);
    const u = String(url);
    const next = patch(u, null);
    if (next === undefined) return res;
    const body = await res.json();
    return new Response(JSON.stringify(patch(u, body)), {
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
  await screen.findByRole("heading", { level: 1 });
}

afterEach(() => vi.restoreAllMocks());

const LINE = /Comparisons start Dec 27, when the window before has data/;

describe("Comparisons start, from the server's date", () => {
  it("names the hour for a 24-hour window and the day otherwise", () => {
    const at = new Date("2026-11-17T18:00:00Z");
    const hour = at.toLocaleTimeString("en-US", { hour: "numeric" });
    expect(compareLine(false, at.toISOString(), "the previous 24 hours")).toBe(
      `Comparisons start Nov 17, ${hour}, when the window before has data`,
    );
    expect(compareLine(false, at.toISOString(), "the previous 7 days")).toBe(
      "Comparisons start Nov 17, when the window before has data",
    );
    expect(compareLine(false, null, "the previous 7 days")).toBe("No comparison yet");
  });

  it("on Agents", async () => {
    await openWith("/agents", (u, body) =>
      u.includes("/api/agents/overview") ? body && { ...body, history: NOT_COMPARED } : undefined,
    );
    expect(await screen.findByText(LINE)).toBeVisible();
  });

  it("on AI Watch", async () => {
    await openWith("/dashboard", (u, body) =>
      u.includes("/api/ai/watch/summary")
        ? body && { ...body, compared: false, since: NOT_COMPARED.since, starts: STARTS }
        : undefined,
    );
    const watch = await screen.findByRole("region", { name: "AI Watch" });
    expect(watch).toHaveTextContent(LINE);
  });

  it("on Microsoft 365", async () => {
    await openWith("/m365", (u, body) =>
      u.includes("/api/m365/overview") ? body && { ...body, history: NOT_COMPARED } : undefined,
    );
    expect(await screen.findByText(LINE)).toBeVisible();
  });
});
