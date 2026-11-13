import { act, render, renderHook, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FilterBar, TIME_PRESETS, type Segment } from "@/components/FilterBar";
import { useFilters } from "@/lib/filters";

const STATES: Segment<"open" | "closed">[] = [
  { id: "open", label: "Open", count: 7 },
  { id: "closed", label: "Closed" },
];

afterEach(() => window.history.replaceState(null, "", "/"));

describe("FilterBar (DESIGN.md 6.0, redesign build row 6)", () => {
  it("offers the same five time presets, 1 hour first", () => {
    expect(TIME_PRESETS.map((p) => p.label)).toEqual([
      "1 hour",
      "24 hours",
      "7 days",
      "30 days",
      "Custom",
    ]);
    const onChange = vi.fn();
    render(<FilterBar label="Filter rows" time={{ value: "24h", onChange }} isDefault />);
    const time = screen.getByRole("group", { name: "Time" });
    expect(within(time).getByRole("button", { name: "1 hour" })).toBeVisible();
    expect(within(time).getByRole("button", { name: "24 hours" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("keeps the fixed order: Time, State, facets, text box, then the count and Columns", () => {
    render(
      <FilterBar
        label="Filter alerts"
        time={{ value: "7d", onChange: () => undefined }}
        state={{ value: "open", options: STATES, onChange: () => undefined }}
        facets={[
          {
            name: "Severity",
            value: "high",
            options: [
              { id: "", label: "Any" },
              { id: "high", label: "High" },
            ],
            onChange: () => undefined,
          },
        ]}
        text={{ label: "Person, device, or source", value: "", onChange: () => undefined }}
        count="7 alerts"
        columns={<button type="button">Columns</button>}
        isDefault
      />,
    );
    const bar = screen.getByRole("group", { name: "Filter alerts" });
    const parts = [
      within(bar).getByRole("group", { name: "Time" }),
      within(bar).getByRole("group", { name: "State" }),
      within(bar).getByRole("combobox", { name: "Severity" }),
      within(bar).getByRole("textbox", { name: "Person, device, or source" }),
      within(bar).getByText("7 alerts"),
      within(bar).getByRole("button", { name: "Columns" }),
    ];
    for (let i = 1; i < parts.length; i += 1)
      expect(
        (parts[i - 1] as HTMLElement).compareDocumentPosition(parts[i] as HTMLElement) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    // State is a segmented control with its counts; a facet reads "Name Value".
    expect(within(bar).getByRole("button", { name: "Open 7" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const facet = within(bar).getByRole("combobox", { name: "Severity" }).closest("label");
    expect(facet).toHaveTextContent(/^Severity/);
    expect(within(bar).getByRole("combobox", { name: "Severity" })).toHaveValue("high");
  });

  it("shows Reset only while the filters differ from the default", async () => {
    const onReset = vi.fn();
    const { rerender } = render(<FilterBar label="Filter rows" onReset={onReset} isDefault />);
    expect(screen.queryByRole("button", { name: "Reset" })).toBeNull();
    rerender(<FilterBar label="Filter rows" onReset={onReset} isDefault={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(onReset).toHaveBeenCalledOnce();
  });
});

describe("Filter state in the address (useFilters)", () => {
  const defaults = { state: "open", sev: "", q: "" };
  const here = () => window.location.pathname + window.location.hash;

  it("reads the fragment, leaves defaults out, and keeps other state such as the open item", () => {
    window.history.replaceState(null, "", "/alerts#sev=high&item=a1");
    const { result } = renderHook(() => useFilters(defaults));
    expect(result.current.values).toEqual({ state: "open", sev: "high", q: "" });
    expect(result.current.isDefault).toBe(false);
    act(() => result.current.set("state", "closed"));
    expect(here()).toBe("/alerts#sev=high&item=a1&state=closed");
    act(() => result.current.set("state", "open"));
    expect(here()).toBe("/alerts#sev=high&item=a1");
    act(() => result.current.reset());
    expect(here()).toBe("/alerts#item=a1");
    expect(result.current.isDefault).toBe(true);
  });

  it("does not add a step to Back for every letter typed in the text box", () => {
    window.history.replaceState(null, "", "/alerts");
    const { result } = renderHook(() => useFilters(defaults));
    const before = window.history.length;
    act(() => result.current.set("q", "w", true));
    act(() => result.current.set("q", "ws", true));
    expect(here()).toBe("/alerts#q=ws");
    expect(window.history.length).toBe(before);
    act(() => result.current.set("q", "", true));
    expect(here()).toBe("/alerts");
  });

  it("stays on the tab the person is on, and keeps the query string", () => {
    window.history.replaceState(null, "", "/agents/sessions?from=mail#session=s1");
    const { result } = renderHook(() =>
      useFilters({ tool: "", flags: "" }, { flags: ["", "flagged"] }),
    );
    act(() => result.current.set("tool", "Bash"));
    expect(window.location.pathname + window.location.search + window.location.hash).toBe(
      "/agents/sessions?from=mail#session=s1&tool=Bash",
    );
    // A value outside the allowed list reads as the default.
    window.history.replaceState(null, "", "/agents/sessions#flags=loud");
    const second = renderHook(() =>
      useFilters({ tool: "", flags: "" }, { flags: ["", "flagged"] }),
    );
    expect(second.result.current.values.flags).toBe("");
    expect(second.result.current.isDefault).toBe(true);
  });
});
