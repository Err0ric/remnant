import { describe, expect, it } from "vitest";
import { AREAS, areaOf } from "@/lib/nav";

describe("Pages (ADR-0052 section 3.2)", () => {
  it("is one page per rail entry, with a page's tabs in its header", () => {
    expect(AREAS.map((a) => a.label)).toEqual([
      "Dashboard",
      "Alerts",
      "Logs",
      "Ask AI",
      "People & devices",
      "AI usage",
      "Agents",
      "Health",
    ]);
    const tabs = AREAS.flatMap((a) => a.tabs.map((t) => t.label));
    expect(tabs).toContain("Collectors"); // log collectors, apart from the Agents page
    expect(tabs).not.toContain("Endpoint agents");
    // Saved searches is a tab of Logs, not a page of the rail.
    expect(areaOf("saved", "")?.area.id).toBe("logs");
    expect(areaOf("logs", "")?.tab.label).toBe("Search");
    // Microsoft 365 is three views of Logs, not an area.
    expect(areaOf("m365", "mail")?.area.id).toBe("logs");
    expect(areaOf("m365", "mail")?.tab.label).toBe("Microsoft 365 mail");
    expect(areaOf("investigate", "")?.area.label).toBe("People & devices");
    // Detect folds into Alerts.
    expect(areaOf("rules", "")?.area.id).toBe("alerts");
    expect(areaOf("schedules", "")?.area.id).toBe("alerts");
    expect(areaOf("agents", "mcp")?.tab.label).toBe("MCP servers");
  });
});

describe("/ai/watch (owner, 2026-10-31)", () => {
  it("opens Settings > AI watch and catalog, where AI Watch is set up", async () => {
    const { canonical, pageFromPath } = await import("@/lib/route");
    expect(pageFromPath("/ai/watch")).toBe("aisettings");
    window.history.replaceState(null, "", "/ai/watch");
    expect(canonical()).toBe("/ai-settings");
    window.history.replaceState(null, "", "/");
  });
});
