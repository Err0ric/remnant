import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { VendorAlerts } from "@/features/alerts/VendorAlerts";

function ids(from: number, n: number) {
  return Array.from({ length: n }, (_, i) => ({
    product: "ExampleCorp EdgeSensor",
    alert_id: `B-${String(from + i).padStart(5, "0")}`,
  }));
}

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <VendorAlerts itemId="item-1" />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("An external alert's vendor alerts (D228)", () => {
  it("shows the count and the first 50, and pages the rest only on Show all", async () => {
    const page = vi
      .spyOn(api, "alertIds")
      .mockImplementation(async (_id, offset = 0, limit = 50) => ({
        count: 5_000,
        ids: ids(offset, Math.min(limit, 5_000 - offset)),
      }));
    const events = vi.spyOn(api, "alertEvents");
    show();
    expect(await screen.findByText("(5,000)")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Vendor alert IDs" });
    expect(list.children).toHaveLength(50);
    expect(page).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: /Show all \(4,950 more/ }));
    await waitFor(() => expect(list.children).toHaveLength(250));
    expect(page).toHaveBeenLastCalledWith("item-1", 50, 200);
    expect(events).not.toHaveBeenCalled(); // events load only when asked
  });

  it("loads the alert events from the server on click, shown as text", async () => {
    vi.spyOn(api, "alertIds").mockResolvedValue({ count: 1, ids: ids(0, 1) });
    const events = vi.spyOn(api, "alertEvents").mockResolvedValue({
      columns: ["alert_id", "message"],
      rows: [["B-00000", "<b>Credential dumping</b>"]],
      elapsed_ms: 4,
    });
    show();
    await userEvent.click(await screen.findByRole("button", { name: "Show alert events" }));
    expect(events).toHaveBeenCalledWith("item-1");
    expect(await screen.findByText("<b>Credential dumping</b>")).toBeInTheDocument();
  });
});
