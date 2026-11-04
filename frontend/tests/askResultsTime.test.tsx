import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AskResults, isIsoTime } from "@/features/ask/AskResults";
import type { QueryResult } from "@/lib/api";

const result: QueryResult = {
  columns: ["person", "sessions", "last_seen"],
  rows: [["dana@example.org", 3, "2026-10-21T09:05:01.123+00:00"]],
  row_count: 1,
  truncated: false,
  elapsed_ms: 4,
  executed_sql: "SELECT 1",
  sources: [],
};

describe("Ask results times (owner, 2026-11-04)", () => {
  it("shows a time as the app does, local with UTC on hover, never the raw string", () => {
    render(<AskResults result={result} />);
    const table = screen.getByRole("table", { name: "Results" });
    expect(within(table).queryByText(/2026-10-21T/)).toBeNull();
    const t = within(table).getByText("Oct 21, 9:05 AM"); // tests run in UTC
    expect(t.tagName).toBe("TIME");
    expect(t).toHaveAttribute("title", expect.stringMatching(/^2026-10-21 09:05 UTC$/));
  });

  it("only strings with a zone are times", () => {
    expect(isIsoTime("2026-10-21T09:05:01Z")).toBe(true);
    expect(isIsoTime("2026-10-21 09:05:01+00:00")).toBe(true);
    expect(isIsoTime("2026-10-21")).toBe(false);
    expect(isIsoTime("2026-10-21T09:05:01")).toBe(false);
    expect(isIsoTime("ws-0042")).toBe(false);
    expect(isIsoTime(42)).toBe(false);
  });
});
