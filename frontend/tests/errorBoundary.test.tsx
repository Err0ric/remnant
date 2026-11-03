import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary, PageBoundary } from "@/components/ErrorBoundary";
import { GUARD_MS, RELOAD_KEY, isChunkError, reloadOnce } from "@/lib/chunkReload";
import { resetReports, scrub } from "@/lib/clientErrors";

/** Owner 2026-11-02: a crash never leaves a blank page; a missing chunk reloads once. */
function Boom(): never {
  throw new Error('Cannot read properties of undefined (reading "alice@example.com")');
}

afterEach(() => {
  vi.restoreAllMocks();
  resetReports();
});

function quiet() {
  vi.spyOn(console, "error").mockImplementation(() => undefined); // React logs the throw
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
}

describe("Error boundaries", () => {
  it("shows an error card for one failing panel while the rest renders, and reports it", () => {
    const fetch = quiet();
    render(
      <div>
        <ErrorBoundary label="Identity">
          <Boom />
        </ErrorBoundary>
        <ErrorBoundary label="Detections">
          <p>Detections are here</p>
        </ErrorBoundary>
      </div>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/^Identity could not be shown/);
    expect(screen.getByRole("alert")).toHaveTextContent(/error id e-[0-9a-f]{6}/);
    expect(screen.getByText("Detections are here")).toBeVisible();
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe("/api/client-errors");
    const body = JSON.parse(String(init?.body)) as Record<string, string>;
    expect(body).toMatchObject({ kind: "panel", name: "Error" });
    // No record content: the quoted value is gone.
    expect(body.message).not.toContain("alice");
  });

  it("shows Something went wrong with Reload for a page, never a blank page", () => {
    quiet();
    render(
      <PageBoundary>
        <Boom />
      </PageBoundary>,
    );
    expect(
      screen.getByRole("heading", { name: "Something went wrong on this page" }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Reload" })).toBeVisible();
  });

  it("scrubs quoted text, emails, and addresses from reported messages", () => {
    expect(scrub("bad 'x' from bob@example.com at 192.0.2.7")).toBe("bad … from … at …");
  });
});

describe("Chunk reload guard", () => {
  it("knows a chunk load failure", () => {
    expect(isChunkError(new TypeError("Failed to fetch dynamically imported module: /a.js"))).toBe(
      true,
    );
    expect(isChunkError(new Error("Importing a module script failed."))).toBe(true);
    expect(isChunkError(new Error("x is undefined"))).toBe(false);
  });

  it("reloads once, then not again within the guard, then again after it", () => {
    const kept = new Map<string, string>();
    const store = {
      getItem: (k: string) => kept.get(k) ?? null,
      setItem: (k: string, v: string) => void kept.set(k, v),
    };
    const reload = vi.fn();
    expect(reloadOnce(store, reload, 1_000_000)).toBe(true);
    expect(kept.get(RELOAD_KEY)).toBe("1000000");
    expect(reloadOnce(store, reload, 1_000_000 + 5_000)).toBe(false); // would loop
    expect(reload).toHaveBeenCalledTimes(1);
    expect(reloadOnce(store, reload, 1_000_000 + GUARD_MS + 1)).toBe(true);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("never reloads when session storage is unavailable", () => {
    const reload = vi.fn();
    expect(reloadOnce(null, reload)).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });
});
