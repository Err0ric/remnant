import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { VendorAlertNotify } from "@/features/sources/VendorAlertNotify";

function show(
  canManage = true,
  pause: { paused_since: string; held: Record<string, number> } | null = null,
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <VendorAlertNotify sourceId="edr" pause={pause} canManage={canManage} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("Vendor alert messages per source (D231)", () => {
  it("starts off at High, and saves the switch, targets, and minimum", async () => {
    vi.spyOn(api, "alertTargets").mockResolvedValue([{ target_id: "t1", name: "Relay" }] as Awaited<
      ReturnType<typeof api.alertTargets>
    >);
    vi.spyOn(api, "alertNotify").mockResolvedValue({
      notify: false,
      target_ids: [],
      min_severity: "high",
    });
    const save = vi.spyOn(api, "setAlertNotify").mockImplementation(async (_id, body) => body);
    show();
    await userEvent.click(screen.getByRole("button", { name: "Vendor alert messages for edr" }));
    const box = await screen.findByRole("checkbox", { name: "Notify alert targets" });
    expect(box).not.toBeChecked();
    const level = screen.getByRole("combobox", { name: "Minimum severity" });
    await waitFor(() => expect(level).toHaveValue("high"));
    expect(level).toBeDisabled();
    await userEvent.click(box);
    await userEvent.click(await screen.findByRole("checkbox", { name: "Relay" }));
    await userEvent.selectOptions(level, "critical");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith("edr", {
        notify: true,
        target_ids: ["t1"],
        min_severity: "critical",
      }),
    );
  });

  it("shows a pause with its held counts to everyone, and no setting to non-admins", () => {
    show(false, { paused_since: "2026-11-09T21:00:00+00:00", held: { medium: 3, low: 1 } });
    expect(screen.getByText(/3 medium, 1 low held/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
