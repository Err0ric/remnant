import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "@/lib/api";
import { FacetSidebar } from "@/features/search/FacetSidebar";

function show(total: { count: number; more: boolean } | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <p>results stay here</p>
      <FacetSidebar request={{ text: "failed" }} onTerm={() => undefined} total={total} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("Logs fields when counting times out (owner priority, 2026-11-14)", () => {
  it("says so plainly, keeps the page, and counts again on Retry", async () => {
    const facets = vi
      .spyOn(api, "facets")
      .mockRejectedValueOnce(new ApiError(408, "The query took longer than 10 s", "query_timeout"))
      .mockResolvedValueOnce({
        facets: [{ field: "source_id", values: [{ value: "fw", count: 3 }] }],
        elapsed_ms: 5,
      });
    show();
    expect(
      await screen.findByText(
        "Counting fields took too long for this range. The results are not affected.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("results stay here")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("fw")).toBeInTheDocument();
    expect(facets).toHaveBeenCalledTimes(2);
  });

  it("names the days and the items when the counts are from the newest days (P6)", async () => {
    vi.spyOn(api, "facets").mockResolvedValueOnce({
      facets: [{ field: "source_id", values: [{ value: "fw", count: 159 }] }],
      elapsed_ms: 5,
      sampled_days: 4,
      sampled_items: 159,
      sampled_skipped: false,
    });
    show({ count: 1133, more: false });
    expect(
      await screen.findByText(
        "Counts from the newest 4 days only (159 of 1,133 items): the whole range took too long to count. The results are not affected.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("fw")).toBeInTheDocument();
  });

  it("says the days had matches when newer days held none, with the card's own total", async () => {
    vi.spyOn(api, "facets").mockResolvedValueOnce({
      facets: [{ field: "source_id", values: [{ value: "fw", count: 420 }] }],
      elapsed_ms: 5,
      sampled_days: 1,
      sampled_items: 420,
      sampled_skipped: true,
    });
    show({ count: 10000, more: true });
    expect(
      await screen.findByText(
        "Counts from the newest day with matches only (420 of 10,000+ items): the whole range took too long to count. The results are not affected.",
      ),
    ).toBeInTheDocument();
  });

  it("never shows a part larger than its whole when the results stop at their limit", async () => {
    vi.spyOn(api, "facets").mockResolvedValueOnce({
      facets: [{ field: "source_id", values: [{ value: "fw", count: 70000 }] }],
      elapsed_ms: 5,
      sampled_days: 2,
      sampled_items: 70000,
      sampled_skipped: false,
    });
    show({ count: 10000, more: true });
    expect(
      await screen.findByText(
        "Counts from the newest 2 days only (70,000 items counted; the results stop at 10,000): the whole range took too long to count. The results are not affected.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/of 10,000\+/)).toBeNull();
  });

  it("says no match was reached in time, never that nothing is countable", async () => {
    vi.spyOn(api, "facets").mockResolvedValueOnce({
      facets: [],
      elapsed_ms: 5,
      sampled_days: 0,
      sampled_items: 0,
      sampled_skipped: true,
    });
    show({ count: 420, more: false });
    expect(
      await screen.findByText(
        "None of the matches fell in the days that could be counted in time. The results are not affected.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/No countable fields/)).toBeNull();
  });

  it("says nothing more when the counts cover the whole range", async () => {
    vi.spyOn(api, "facets").mockResolvedValueOnce({
      facets: [{ field: "source_id", values: [{ value: "fw", count: 3 }] }],
      elapsed_ms: 5,
      sampled_days: null,
    });
    show();
    expect(await screen.findByText("fw")).toBeInTheDocument();
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("shows any other error's own message, with Retry", async () => {
    vi.spyOn(api, "facets").mockRejectedValueOnce(new Error("Something else broke"));
    show();
    expect(await screen.findByText("Something else broke")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
