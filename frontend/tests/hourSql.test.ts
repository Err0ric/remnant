import { describe, expect, it } from "vitest";
import { hourSql } from "@/lib/searchSeed";

describe("hourSql", () => {
  it("covers one UTC hour for one source", () => {
    const sql = hourSql("win_dc", "2026-10-19T23:00:00+00:00")!;
    expect(sql).toContain("source_id = 'win_dc'");
    expect(sql).toContain(">= TIMESTAMPTZ '2026-10-19T23:00:00+00:00'");
    expect(sql).toContain("< TIMESTAMPTZ '2026-10-20T00:00:00+00:00'");
  });

  it("quotes the source id and refuses anything but an hour start", () => {
    expect(hourSql("a'b", "2026-10-19T23:00:00Z")).toContain("source_id = 'a''b'");
    expect(hourSql("x", "2026-10-19T23:30:00Z")).toBeNull();
    expect(hourSql("x", "'; DROP")).toBeNull();
  });
});
