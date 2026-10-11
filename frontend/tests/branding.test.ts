import { describe, expect, it, vi } from "vitest";
import { mockApi } from "./mockApi";

describe("branding", () => {
  it("reads the product name from the API and sets the document title", async () => {
    mockApi("Codename");
    vi.resetModules();
    const branding = await import("@/lib/branding");
    await branding.loadBranding();
    expect(branding.PRODUCT_NAME).toBe("Codename");
    expect(document.title).toBe("Codename");
  });

  it("falls back to a neutral label when the API is unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    vi.resetModules();
    const branding = await import("@/lib/branding");
    await branding.loadBranding();
    expect(branding.PRODUCT_NAME).toBe("Console");
  });
});
