import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Card } from "@/components/Card";
import { CardAction } from "@/components/CardAction";

describe("Card anatomy (DESIGN.md 7, D254)", () => {
  it("draws one title row: title, (i), note, then the action last", async () => {
    const open = vi.fn();
    render(
      <Card
        title="Top services"
        level="panel"
        about="Distinct services in the window."
        note="last 7 days"
        action={<CardAction onClick={open}>View all</CardAction>}
      >
        <p>rows</p>
      </Card>,
    );
    const card = screen.getByRole("region", { name: "Top services" });
    const head = card.querySelector<HTMLElement>("[data-card-header]")!;
    const parts = [...head.children];
    expect(parts[0]).toBe(within(head).getByRole("heading", { level: 3, name: "Top services" }));
    expect(parts[1]).toBe(
      within(head).getByRole("img", { name: /^How this is counted: Distinct services/ }),
    );
    expect(parts[2]).toHaveTextContent("last 7 days");
    const action = within(head).getByRole("button", { name: "View all" });
    expect(parts.at(-1)).toContainElement(action);
    // The body comes after the header row, never inside it.
    expect(within(head).queryByText("rows")).toBeNull();
    // Keyboard: the (i), then the action.
    await userEvent.tab();
    await userEvent.tab();
    expect(action).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(open).toHaveBeenCalledTimes(1);
  });

  it("has a header of one height with no fill, at either level", () => {
    render(
      <>
        <Card title="AI Watch" note="Changes against the previous 7 days" />
        <Card title="Top services" level="panel" />
      </>,
    );
    const section = screen.getByRole("region", { name: "AI Watch" });
    expect(within(section).getByRole("heading", { level: 2 }).dataset.title).toBe("section");
    expect(
      within(screen.getByRole("region", { name: "Top services" })).getByRole("heading", {
        level: 3,
      }).dataset.title,
    ).toBe("panel");
    for (const head of document.querySelectorAll<HTMLElement>("[data-card-header]")) {
      expect(head.className).toContain("h-10");
      expect(head.className).toMatch(/\bpx-3\b/);
      expect(head.className).toMatch(/\bpy-2\b/);
      expect(head.className).not.toMatch(/(^|\s)bg-/);
    }
  });

  it("names the region apart from the title when asked, and leaves out what is not given", () => {
    render(<Card title="Sessions" label="Agent sessions" />);
    const card = screen.getByRole("region", { name: "Agent sessions" });
    const head = card.querySelector<HTMLElement>("[data-card-header]")!;
    expect(head.children).toHaveLength(1);
    expect(within(head).getByRole("heading", { name: "Sessions" })).toBeVisible();
  });
});
