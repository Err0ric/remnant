import { describe, expect, it } from "vitest";
import { NAV_GROUPS } from "@/lib/nav";

describe("Left nav (F48)", () => {
  it("puts daily work first and Health last, with one label per meaning", () => {
    expect(NAV_GROUPS.map((g) => g.label)).toEqual([
      "General",
      "Investigate",
      "Detect",
      "AI",
      "System",
    ]);
    const labels = NAV_GROUPS.flatMap((g) =>
      g.items.flatMap((i) => [i.label, ...(i.sections ?? []).map((s) => s.label)]),
    );
    expect(labels.filter((l) => l === "Agents")).toHaveLength(1); // AI agents only
    expect(labels).toContain("Endpoint agents");
  });
});
