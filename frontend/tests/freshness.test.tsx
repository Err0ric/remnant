import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { Freshness, ago } from "@/components/shell/Freshness";

function Page({ updated }: { updated: string }) {
  useQuery({ queryKey: ["view"], queryFn: () => ({ updated_at: updated }) });
  return <Freshness />;
}

describe("Freshness", () => {
  it("says seconds for a background-refreshed view", () => {
    expect(ago(2_000)).toBe("just now");
    expect(ago(40_000)).toBe("40 s ago");
    expect(ago(150_000)).toBe("3 min ago");
  });

  it("shows when the server computed the page's numbers (D147)", async () => {
    const client = new QueryClient();
    const updated = new Date(Date.now() - 42_000).toISOString();
    render(
      <QueryClientProvider client={client}>
        <Page updated={updated} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText(/Updated 4\d s ago/)).toBeInTheDocument();
  });
});
