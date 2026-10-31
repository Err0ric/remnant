import { describe, expect, it } from "vitest";
import { AREAS, areaOf } from "@/lib/nav";

describe("Areas (ADR-0038)", () => {
  it("reads in the morning's order, one row per area, with tabs in the page header", () => {
    expect(AREAS.map((a) => a.label)).toEqual([
      "Dashboard",
      "Alerts",
      "Microsoft 365",
      "Investigate",
      "AI usage",
      "Agents",
      "Health",
    ]);
    const tabs = AREAS.flatMap((a) => a.tabs.map((t) => t.label));
    expect(tabs).toContain("Endpoint agents"); // log collectors, apart from the Agents area
    expect(tabs).toContain("People & devices");
    // Detect folds into Alerts.
    expect(areaOf("rules", "")?.area.id).toBe("alerts");
    expect(areaOf("schedules", "")?.area.id).toBe("alerts");
    expect(areaOf("agents", "mcp")?.tab.label).toBe("MCP servers");
  });
});
