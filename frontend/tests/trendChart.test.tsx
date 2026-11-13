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

  it("draws lines only, each part of a stack at its own value, and still gives the total", async () => {
    const { container } = render(
      <TrendChart
        title="AI use"
        stacked
        series={[
          { key: "a", label: "Approved", values: [4, 4], color: "local-tx" },
          { key: "n", label: "Not approved", values: [1, 3], color: "warn" },
        ]}
        pointLabel={(i) => `day ${i + 1}`}
        axisLabel={(i) => `day ${i + 1}`}
        summary="AI use"
      />,
    );
    const paths = [...container.querySelectorAll("svg path")];
    expect(paths.length).toBe(2);
    for (const path of paths) {
      expect(path.getAttribute("fill")).toBe("none");
      expect(path.getAttribute("stroke-width")).toBe("1.5");
      expect(path.hasAttribute("fill-opacity")).toBe(false);
      expect(path.getAttribute("d")).not.toMatch(/Z$/);
    }
    // Not cumulative: every line is where the same series is drawn with no stacking.
    const plain = render(
      <TrendChart
        title="AI use, plain"
        series={[
          { key: "a", label: "Approved", values: [4, 4], color: "local-tx" },
          { key: "n", label: "Not approved", values: [1, 3], color: "warn" },
        ]}
        pointLabel={(i) => `day ${i + 1}`}
        axisLabel={(i) => `day ${i + 1}`}
        summary="AI use, plain"
      />,
    );
    const plainPaths = [...plain.container.querySelectorAll("svg path")];
    expect(paths.map((p) => p.getAttribute("d"))).toEqual(
      plainPaths.map((p) => p.getAttribute("d")),
    );
    plain.unmount();
    screen.getByRole("img").focus();
    await userEvent.keyboard("{End}");
    expect(screen.getByRole("tooltip")).toHaveTextContent("7");
  });
});
