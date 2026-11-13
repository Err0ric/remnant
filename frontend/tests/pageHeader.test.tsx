import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PageHeader, type HeaderAction } from "@/components/shell/PageHeader";

const act = (label: string, onClick = vi.fn()): HeaderAction => ({ label, onClick });

afterEach(() => window.history.replaceState(null, "", "/"));

describe("PageHeader (DESIGN.md 5 and 6.0, redesign build row 2)", () => {
  it("shows the page's name as the one h1, with the count beside it", () => {
    window.history.replaceState(null, "", "/me");
    render(<PageHeader title="Your account" count="3 tokens" />);
    const headings = screen.getAllByRole("heading", { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent("Your account");
    expect(headings[0]).toHaveClass("text-lg");
    expect(screen.getByText("3 tokens")).toBeVisible();
  });

  it("has at most one filled button, last, after the secondary buttons and the menu", () => {
    window.history.replaceState(null, "", "/me");
    const { container } = render(
      <PageHeader
        title="Your account"
        secondary={[act("Export"), act("Columns"), act("Third")]}
        menu={[act("Archive")]}
        primary={act("New token")}
      />,
    );
    const actions = container.querySelector("[data-header-actions]") as HTMLElement;
    const buttons = within(actions).getAllByRole("button");
    expect(buttons.map((b) => b.getAttribute("aria-label") ?? b.textContent)).toEqual([
      "Export",
      "Columns",
      "More actions",
      "New token",
    ]);
    const filled = buttons.filter((b) => /\bbg-accent\b/.test(b.className));
    expect(filled).toHaveLength(1);
    expect(filled[0]).toHaveTextContent("New token");
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("puts a third secondary button and the menu items behind More, and Esc closes it", async () => {
    window.history.replaceState(null, "", "/me");
    const third = vi.fn();
    render(
      <PageHeader
        title="Your account"
        secondary={[act("Export"), act("Columns"), act("Third", third)]}
        menu={[act("Archive")]}
      />,
    );
    expect(screen.queryByRole("menu")).toBeNull();
    const more = screen.getByRole("button", { name: "More actions" });
    await userEvent.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    const items = within(screen.getByRole("menu")).getAllByRole("menuitem");
    expect(items.map((i) => i.textContent)).toEqual(["Third", "Archive"]);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    await userEvent.click(more);
    await userEvent.click(screen.getByRole("menuitem", { name: "Third" }));
    expect(third).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("works from the keyboard and closes on a click outside", async () => {
    window.history.replaceState(null, "", "/me");
    render(
      <>
        <PageHeader title="Your account" menu={[act("Archive"), act("Rename"), act("Delete")]} />
        <p>elsewhere</p>
      </>,
    );
    const more = screen.getByRole("button", { name: "More actions" });
    more.focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("menuitem", { name: "Archive" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Archive" })).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(more).toHaveFocus();
    await userEvent.click(more);
    expect(screen.getByRole("menu")).toBeVisible();
    await userEvent.click(screen.getByText("elsewhere"));
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("is read and tabbed in the order title, tabs, actions", async () => {
    window.history.replaceState(null, "", "/alerts");
    const { container } = render(
      <PageHeader title="Alerts" secondary={[act("Export")]} primary={act("Close")} />,
    );
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1).toHaveTextContent("Alerts");
    const tabs = screen.getByRole("navigation", { name: "Alerts tabs" });
    const actions = container.querySelector("[data-header-actions]") as HTMLElement;
    const follows = (a: Node, b: Node) =>
      Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(follows(h1, tabs)).toBe(true);
    expect(follows(tabs, actions)).toBe(true);
    // Tab moves through the tab links first, then the buttons.
    await userEvent.tab();
    expect(tabs.contains(document.activeElement)).toBe(true);
    for (let i = 0; i < within(tabs).getAllByRole("link").length; i += 1) await userEvent.tab();
    expect(document.activeElement).toHaveTextContent("Export");
    await userEvent.tab();
    expect(document.activeElement).toHaveTextContent("Close");
  });

  it("never truncates the title, truncates a long count, and gives phones a row of buttons", () => {
    window.history.replaceState(null, "", "/me");
    const { container } = render(
      <PageHeader title="Your account" count="A long status line" secondary={[act("Export")]} />,
    );
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1).toHaveClass("shrink-0", "whitespace-nowrap");
    expect(h1.className).not.toMatch(/truncate/);
    expect(screen.getByText("A long status line")).toHaveClass("min-w-0", "truncate");
    expect(container.querySelector("[data-header-actions]")).toHaveClass(
      "flex-wrap",
      "max-sm:row-start-3",
      "max-sm:col-span-2",
    );
  });

  it("draws no actions row when a page has none", () => {
    window.history.replaceState(null, "", "/me");
    const { container } = render(<PageHeader title="Your account" />);
    expect(container.querySelector("[data-header-actions]")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
