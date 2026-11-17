import { describe, expect, it } from "vitest";
import { columnTemplate } from "@/lib/search";

describe("columnTemplate", () => {
  it("sizes each column from its longest value so every row lines up", () => {
    const cols = ["source_ip", "failed_logins", "message"];
    const rows = [
      ["203.0.113.9", 278, "short"],
      ["198.51.100.200", 264, "a much longer message here"],
    ];
    // Message takes what is left and may shrink to 16ch: it truncates, the others do not.
    expect(columnTemplate(cols, rows, [0, 1, 2])).toBe("32px 17ch 16ch minmax(16ch, 1fr)");
    // Wherever it stands.
    expect(columnTemplate(["message", "n"], [["some text here", 5]], [0, 1])).toBe(
      "32px minmax(16ch, 1fr) 4ch",
    );
  });

  it("caps very long values and gives severity a fixed width", () => {
    const cols = ["severity_id", "raw"];
    const rows = [[3, "x".repeat(500)]];
    // Without a message column the last one takes what is left.
    expect(columnTemplate(cols, rows, [0, 1], 48)).toBe("32px 12ch minmax(16ch, 1fr)");
    expect(columnTemplate(["host", "n"], [["bastion", 5]], [0, 1])).toBe(
      "32px 10ch minmax(4ch, 1fr)",
    );
  });
});

describe("columnTemplate, the flexible column (owner, 2026-11-16)", () => {
  it("lets a long app name shrink instead of the address after it", () => {
    const cols = ["time", "app", "outcome", "src_endpoint_ip"];
    const rows = [
      ["2026-11-15T16:48:33Z", "Office 365 SharePoint Online", "Signed in", "198.51.100.7"],
    ];
    expect(columnTemplate(cols, rows, [0, 1, 2, 3])).toBe("32px 22ch minmax(12ch, 1fr) 12ch 15ch");
  });

  it("leaves a longer last column to give way first", () => {
    const cols = ["app", "result", "permissions"];
    const rows = [["Microsoft Entra Sync Pro", "blocked", "Mail.ReadWrite ".repeat(6)]];
    expect(columnTemplate(cols, rows, [0, 1, 2])).toBe("32px 27ch 10ch minmax(16ch, 1fr)");
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

describe("drill-through SQL for Search (owner, 2026-10-31)", () => {
  it("reads the window through {{start}} and {{end}}, not fixed dates", async () => {
    const { placeholderSql } = await import("@/lib/drill");
    const sql =
      "SELECT * FROM events WHERE x = 1\n  AND t >= TIMESTAMPTZ '{from}' AND t < TIMESTAMPTZ '{to}'";
    expect(placeholderSql(sql)).toBe(
      "SELECT * FROM events WHERE x = 1\n  AND t >= {{start}} AND t < {{end}}",
    );
  });
});
