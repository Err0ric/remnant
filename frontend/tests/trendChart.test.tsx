import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { startIndex, TrendChart } from "@/features/dashboard/TrendChart";

describe("TrendChart (owner, 2026-10-31)", () => {
  it("hatches the days before data starts and marks today as so far", async () => {
    const points = ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"].map(
      (d) => `${d}T00:00:00Z`,
    );
    const begin = startIndex(points, "2026-10-02T09:00:00Z");
    expect(begin).toBe(1);
    expect(startIndex(points, "2026-09-01T00:00:00Z")).toBeUndefined();
    render(
      <TrendChart
        title="Failed sign-ins per day"
        series={[{ key: "f", label: "Failed", values: [0, 3, 5, 1], color: "warn" }]}
        firstWithData={begin}
        partial="so far"
        pointLabel={(i) => points[i]!.slice(5, 10)}
        axisLabel={(i) => points[i]!.slice(5, 10)}
        summary="Failed sign-ins per day"
      />,
    );
    const chart = screen.getByRole("img");
    chart.focus();
    await userEvent.keyboard("{Home}");
    expect(screen.getByRole("tooltip")).toHaveTextContent("10-01: Before the data starts");
    await userEvent.keyboard("{End}");
    expect(screen.getByRole("tooltip")).toHaveTextContent("10-04 (so far): Failed 1");
  });
});
