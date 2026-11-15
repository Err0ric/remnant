import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "@/lib/api";
import { FacetSidebar } from "@/features/search/FacetSidebar";

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <p>results stay here</p>
      <FacetSidebar request={{ text: "failed" }} onTerm={() => undefined} />
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

  it("shows any other error's own message, with Retry", async () => {
    vi.spyOn(api, "facets").mockRejectedValueOnce(new Error("Something else broke"));
    show();
    expect(await screen.findByText("Something else broke")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
