import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SpeedTable } from "@/features/health/SpeedTable";
import { api } from "@/lib/api";

describe("Health > Speed refreshes (D147)", () => {
  it("shows refreshes per hour and the views kept fresh", async () => {
    const hours = Array.from({ length: 24 }, (_, i) => ({
      hour: new Date(Date.UTC(2026, 10, 1, i)).toISOString(),
      refreshes: i === 23 ? 60 : 0,
      failed: i === 23 ? 2 : 0,
    }));
    vi.spyOn(api, "healthSpeed").mockResolvedValue([]);
    vi.spyOn(api, "healthRefreshes").mockResolvedValue({ views: 3, hours });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SpeedTable />
      </QueryClientProvider>,
    );
    const list = await screen.findByRole("list", { name: "Refreshes per hour" });
    expect(list.querySelectorAll("li")).toHaveLength(24);
    expect(screen.getByText(/views kept fresh now/)).toBeTruthy();
    expect(screen.getByText("60")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
  });
});
