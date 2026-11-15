import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { ResultsTable } from "@/features/search/ResultsTable";
import type { QueryResult } from "@/lib/api";

/** 120 events, newest first: "event 1" to "event 120". */
function result(n = 120): QueryResult {
  return {
    columns: ["time", "source_id", "message", "event_id"],
    rows: Array.from({ length: n }, (_, i) => [
      "2026-10-09T23:04:36+00:00",
      "linux_sshd",
      `event ${i + 1}`,
      `id-${i + 1}`,
    ]),
    row_count: n,
    truncated: false,
    elapsed_ms: 1,
    executed_sql: "",
    sources: ["linux_sshd"],
  } as QueryResult;
}

const row = (n: number) => screen.queryByText(`event ${n}`, { exact: true });

afterEach(() => window.localStorage.clear());

describe("Results paging (owner, 2026-11-13: row 51 must be reachable)", () => {
  it("reaches row 51 with Next, by keyboard, and comes back with Previous", async () => {
    render(<ResultsTable result={result()} view="parsed" />);
    expect(row(50)).toBeVisible();
    expect(row(51)).toBeNull();
    // The pager is above and below the rows, beside the count: never only under row 50.
    const pagers = screen.getAllByRole("navigation", { name: "Result pages" });
    expect(pagers).toHaveLength(2);
    for (const p of pagers) expect(p).toHaveTextContent("1 to 50 of 120");
    const next = within(pagers[0]!).getByRole("button", { name: "Next" });
    next.focus();
    await userEvent.keyboard("{Enter}");
    expect(row(51)).toBeVisible();
    expect(row(50)).toBeNull();
    for (const p of pagers) expect(p).toHaveTextContent("51 to 100 of 120");
    await userEvent.click(within(pagers[1]!).getByRole("button", { name: "Next" }));
    expect(row(120)).toBeVisible();
    expect(within(pagers[1]!).getByRole("button", { name: "Next" })).toBeDisabled();
    await userEvent.click(within(pagers[1]!).getByRole("button", { name: "Previous" }));
    expect(row(51)).toBeVisible();
  });

  it("offers 50, 100, or 500 rows a page, and remembers the choice", async () => {
    const { unmount } = render(<ResultsTable result={result()} view="parsed" />);
    const size = screen.getAllByRole("combobox", { name: "Rows per page" })[0]!;
    expect(
      within(size)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["50", "100", "500"]);
    await userEvent.selectOptions(size, "100");
    expect(row(51)).toBeVisible();
    expect(row(101)).toBeNull();
    expect(screen.getAllByRole("navigation", { name: "Result pages" })[0]).toHaveTextContent(
      "1 to 100 of 120",
    );
    unmount();
    render(<ResultsTable result={result()} view="parsed" />);
    expect(row(100)).toBeVisible();
  });

  it("goes back to the first page when the size changes on a later page", async () => {
    render(<ResultsTable result={result()} view="parsed" />);
    const pager = screen.getAllByRole("navigation", { name: "Result pages" })[0]!;
    await userEvent.click(within(pager).getByRole("button", { name: "Next" }));
    await userEvent.selectOptions(within(pager).getByRole("combobox"), "500");
    expect(row(1)).toBeVisible();
    expect(row(120)).toBeVisible();
    expect(within(pager).getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("shows no pager for a result that fits one page of the smallest size", () => {
    render(<ResultsTable result={result(12)} view="parsed" />);
    expect(screen.queryByRole("navigation", { name: "Result pages" })).toBeNull();
    expect(screen.getByText("12 rows")).toBeVisible();
  });

  it("opens another result on its first page", async () => {
    const { rerender } = render(<ResultsTable result={result()} view="parsed" />);
    const next = () =>
      within(screen.getAllByRole("navigation", { name: "Result pages" })[0]!).getByRole("button", {
        name: "Next",
      });
    await userEvent.click(next());
    await userEvent.click(next());
    expect(row(101)).toBeVisible();
    // A rerun that returns 60 rows: row 1, not "51 to 60 of 60".
    rerender(<ResultsTable result={result(60)} view="parsed" />);
    expect(row(1)).toBeVisible();
    expect(screen.getAllByRole("navigation", { name: "Result pages" })[0]).toHaveTextContent(
      "1 to 50 of 60",
    );
  });

  it("keeps the page when a parent redraws the same result as a new object", async () => {
    const r = result();
    const { rerender } = render(<ResultsTable result={{ ...r }} view="parsed" />);
    await userEvent.click(screen.getAllByRole("button", { name: "Next" })[0]!);
    rerender(<ResultsTable result={{ ...r }} view="parsed" />);
    expect(row(51)).toBeVisible();
  });

  it("draws the pager with the theme's tokens, so it follows dark and light", () => {
    // jsdom has no colors to compare; `scripts/check-layout.py` measures the drawn pager
    // in both themes on the demo.
    render(<ResultsTable result={result()} view="parsed" />);
    for (const p of screen.getAllByRole("navigation", { name: "Result pages" })) {
      const next = within(p).getByRole("button", { name: "Next" });
      expect(next).toBeEnabled();
      expect(within(p).getByRole("button", { name: "Previous" })).toBeDisabled();
      for (const token of ["border-border-strong", "text-text"])
        expect(next.className).toContain(token);
      expect(next.className).not.toMatch(/#[0-9a-f]{3,6}/i);
    }
  });
});

describe("Results width (owner, 2026-11-13: Message takes what is left)", () => {
  it("lets the Message column shrink and fills the pane, so the table fits its box", () => {
    render(<ResultsTable result={result()} view="parsed" />);
    const grid = screen.getByRole("treegrid", { name: "Search results" });
    // As wide as its box, and wider only when the fixed columns alone need more.
    expect(grid.className).toContain("w-full");
    expect(grid.className).not.toContain("w-max");
    const first = within(grid).getAllByRole("row")[1]!;
    expect(first.style.gridTemplateColumns).toMatch(/minmax\(\d+ch, 1fr\)$/);
    // The full text is one click away, in the expanded row; the cell carries it on hover.
    expect(screen.getByText("event 1", { exact: true })).toHaveAttribute("title", "event 1");
  });
});
