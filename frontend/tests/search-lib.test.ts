import { describe, expect, it } from "vitest";
import { columnTemplate } from "@/lib/search";

describe("columnTemplate", () => {
  it("sizes each column from its longest value so every row lines up", () => {
    const cols = ["source_ip", "failed_logins", "message"];
    const rows = [
      ["203.0.113.9", 278, "short"],
      ["198.51.100.200", 264, "a much longer message here"],
    ];
    expect(columnTemplate(cols, rows, [0, 1, 2])).toBe("32px 17ch 16ch minmax(29ch, 1fr)");
  });

  it("caps very long values and gives severity a fixed width", () => {
    const cols = ["severity_id", "raw"];
    const rows = [[3, "x".repeat(500)]];
    expect(columnTemplate(cols, rows, [0, 1], 48)).toBe("32px 12ch minmax(51ch, 1fr)");
  });
});

describe("sortRows", () => {
  it("sorts numbers as numbers, text as text, and keeps empty values last", async () => {
    const { sortRows } = await import("@/lib/search");
    const rows = [
      ["b", 10],
      [null, 2],
      ["a", 9],
      ["C", null],
    ];
    expect(sortRows(rows, 1, "asc").map((r) => r[1])).toEqual([2, 9, 10, null]);
    expect(sortRows(rows, 1, "desc").map((r) => r[1])).toEqual([10, 9, 2, null]);
    expect(sortRows(rows, 0, "asc").map((r) => r[0])).toEqual(["a", "b", "C", null]);
    expect(sortRows(rows, 0, "desc").map((r) => r[0])).toEqual(["C", "b", "a", null]);
    expect(rows[0]).toEqual(["b", 10]); // the input is not changed
  });
});
