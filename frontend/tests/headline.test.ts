import { describe, expect, it } from "vitest";
import { flagText, panelLabel, rowNoun } from "@/features/dashboard/headline";
import type { Schedule, ScheduleRunSummary } from "@/lib/api";

const base = { kind: "search", threshold_kind: "above", threshold_value: 0 } as unknown as Schedule;
const run = { row_count: 3, flagged: true, flag_reason: "3 is above 0" } as ScheduleRunSummary;

describe("Panel words (ADR-0034 polish)", () => {
  it("names what a row is instead of 'rows'", () => {
    expect(rowNoun(base, ["src_endpoint_ip", "users"])).toBe("addresses");
    expect(rowNoun(base, ["actor_user_name", "n"])).toBe("people");
    expect(rowNoun(base, ["device_hostname"])).toBe("devices");
    expect(rowNoun(base, ["x"])).toBe("results");
    expect(rowNoun({ ...base, kind: "rule" }, [])).toBe("matches");
    expect(panelLabel({ ...base, headline_label: "sprays" }, ["src"])).toBe("sprays");
  });

  it("says flags in plain words", () => {
    expect(flagText(base, run, ["src_endpoint_ip"])).toBe("3 addresses over threshold (0)");
    expect(flagText({ ...base, threshold_kind: "below", threshold_value: 5 }, run, [])).toBe(
      "3 results, under threshold (5)",
    );
    expect(flagText(base, { ...run, flagged: false }, [])).toBeNull();
  });
});

describe("Range words", () => {
  it("reads like a person would say it", async () => {
    const { rangeWords } = await import("@/features/dashboard/headline");
    expect(rangeWords(1440)).toBe("Last 24 hours");
    expect(rangeWords(10080)).toBe("Last 7 days");
    expect(rangeWords(527040)).toBe("Last 12 months");
    expect(rangeWords(null)).toBeNull();
  });
});
