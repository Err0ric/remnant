import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminChanges, changes, cycleGroups, cycleLine } from "@/features/m365/AdminChanges";
import { api, type M365Overview, type QueryResult } from "@/lib/api";

const COLUMNS = [
  "time",
  "actor",
  "actor_kind",
  "app_id",
  "operation",
  "target",
  "status",
  "events",
  "event_ids",
  "changed",
  "provisioning",
  "service",
  "rank",
];
const SP = "22222222-2222-4222-8222-222222222222";

function cycle(time: string, status = "Success", service = "Example Directory Sync") {
  return [
    time,
    service,
    "app",
    null,
    "execution",
    null,
    status,
    1,
    [`e-${time}`],
    "",
    true,
    service,
    0,
  ];
}

const RESULT: QueryResult = {
  columns: COLUMNS,
  rows: [
    [
      "2026-10-30T09:00:00+00:00",
      "admin@example.com",
      "person",
      null,
      "add member to role",
      "Helpdesk Administrator",
      "Success",
      2,
      ["e-1", "e-2"],
      "",
      false,
      "admin@example.com",
      5,
    ],
    [
      "2026-10-30T07:00:00+00:00",
      "Example HR Connector",
      "app",
      SP,
      "update user",
      "pat@example.com",
      "Success",
      1,
      ["e-3"],
      "Department, JobTitle",
      false,
      "Example HR Connector",
      0,
    ],
    cycle("2026-10-30T08:00:00+00:00"),
    cycle("2026-10-30T08:10:00+00:00"),
    cycle("2026-10-30T08:20:00+00:00", "Failure"),
    cycle("2026-10-29T08:00:00+00:00"),
  ],
  row_count: 6,
  truncated: false,
  elapsed_ms: 3,
  executed_sql: "",
} as unknown as QueryResult;

const M = {
  start: "2026-10-23T12:00:00+00:00",
  end: "2026-10-30T12:00:00+00:00",
  lists: { admin: "SELECT 1 WHERE TIMESTAMPTZ '{from}' < TIMESTAMPTZ '{to}'" },
} as unknown as M365Overview;

afterEach(() => vi.restoreAllMocks());

describe("Microsoft 365 > Admin (owner, 2026-11-01)", () => {
  it("groups provisioning cycles per service and day and keeps failures apart", () => {
    const { groups, failed } = cycleGroups(changes(RESULT), "UTC");
    expect(groups.map(cycleLine)).toEqual([
      "Example Directory Sync: 3 cycles, 1 failed",
      "Example Directory Sync: 1 cycle, all succeeded",
    ]);
    expect(groups.map((g) => g.day)).toEqual(["Oct 30", "Oct 29"]);
    expect(failed).toHaveLength(1);
  });

  it("shows real changes, hides routine ones until asked, and names apps", async () => {
    vi.spyOn(api, "query").mockResolvedValue(RESULT);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AdminChanges m={M} timeZone="UTC" />
      </QueryClientProvider>,
    );
    const table = await screen.findByRole("table", { name: "Admin changes" });
    expect(within(table).getByText("add member to role")).toBeVisible();
    expect(within(table).queryByText("Example HR Connector")).toBeNull();
    expect(within(table).getByText("Success")).toBeVisible();
    expect(within(table).getByRole("button", { name: "2" })).toHaveAttribute(
      "title",
      "Open 2 events in Search",
    );
    await userEvent.click(screen.getByRole("checkbox", { name: "Hide routine" }));
    const all = screen.getByRole("table", { name: "Admin changes" });
    const hr = within(all).getByText("Example HR Connector").closest("tr")!;
    expect(within(hr).getByText("App")).toBeVisible();
    expect(within(hr).getByText("Department, JobTitle")).toBeVisible();
    await userEvent.click(within(hr).getByRole("button", { name: "Show details" }));
    expect(screen.getByText(SP)).toBeVisible();
    const prov = screen.getByRole("region", { name: "Provisioning" });
    expect(within(prov).getByRole("table", { name: "Failed cycles" })).toBeVisible();
    expect(within(prov).getByText("Example Directory Sync: 3 cycles, 1 failed")).toBeVisible();
  });
});
