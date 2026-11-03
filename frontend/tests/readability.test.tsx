import { QueryClient } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

async function renderAt(path: string) {
  window.history.replaceState(null, "", path);
  const spy = mockApi("Codename", { mode: "login", signedIn: true, role: "admin" });
  vi.resetModules();
  const { loadBranding } = await import("@/lib/branding");
  await loadBranding();
  const { App } = await import("@/app/App");
  render(
    <App
      initialTheme="dark"
      queryClient={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    />,
  );
  return spy;
}

afterEach(() => vi.restoreAllMocks());

describe("Needs attention (owner, 2026-11-02)", () => {
  it("leaves out empty items and flags failed sign-ins only over the threshold", async () => {
    const { attentionItems, count, failedSigninsItem, FAILED_SIGNINS_THRESHOLD } =
      await import("@/features/dashboard/NeedsAttention");
    const kpi = (value: number, before: number | null) => ({
      value,
      before,
      extra: null,
      drill: null,
      extra_drill: null,
    });
    expect(failedSigninsItem(kpi(FAILED_SIGNINS_THRESHOLD, 0))).toBeNull();
    expect(failedSigninsItem(kpi(50, 30))).toBeNull(); // not twice the window before
    expect(failedSigninsItem(kpi(50, 10))?.text).toBe("50 real failed sign-ins");
    expect(failedSigninsItem(kpi(50, null))?.text).toBe("50 real failed sign-ins");
    const items = attentionItems([
      count("a", 0, "open alert", "open alerts", "alerts"),
      count("b", 1, "risky mail rule", "risky mail rules", "m365", "mail"),
      null,
    ]);
    expect(items.map((i) => i.text)).toEqual(["1 risky mail rule"]);
  });

  it("tops the Dashboard and the Microsoft 365 overview with what needs someone", async () => {
    await renderAt("/dashboard");
    const strip = await screen.findByRole("region", { name: "Needs attention" });
    expect(within(strip).getByRole("button", { name: /open alert/ })).toBeVisible();
    expect(within(strip).getByRole("button", { name: "1 blocked app consent" })).toBeVisible();
    // Panels cover their own ranges: the header no longer names one.
    expect(screen.queryByText(/^Last 24 hours, /)).toBeNull();
  });

  it("says when nothing needs attention", async () => {
    const { NeedsAttention } = await import("@/features/dashboard/NeedsAttention");
    render(<NeedsAttention items={[]} />);
    expect(screen.getByRole("region", { name: "Needs attention" })).toHaveTextContent(
      "Nothing needs attention",
    );
  });
});

describe("Zero values are muted, never green (DESIGN.md)", () => {
  it("shows a zero KPI in muted gray", async () => {
    await renderAt("/dashboard");
    const overview = await screen.findByRole("region", { name: "Identity" });
    const zeros = [...overview.querySelectorAll<HTMLElement>("[data-kpi] .text-kpi")].filter(
      (e) => e.textContent === "0",
    );
    expect(zeros.length).toBeGreaterThan(0);
    for (const z of zeros) {
      expect(z).toHaveClass("text-text-muted");
      expect(z).not.toHaveClass("text-ok");
    }
  });
});
