import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EntityLink, EntityList } from "@/components/EntityLink";
import { oneLine, splitValue, Truncate } from "@/components/Truncate";
import { COPYING, installCopyWhole } from "@/lib/copyWhole";
import { clipMiddle } from "@/features/investigate/LaneGraph";

afterEach(() => vi.restoreAllMocks());

const parts = (el: Element) => ({
  head: el.querySelector<HTMLElement>('[data-part="head"]')!,
  tail: el.querySelector<HTMLElement>('[data-part="tail"]')!,
});

const cutsBox = (el: HTMLElement) =>
  expect(el).toHaveClass("min-w-0", "overflow-hidden", "text-ellipsis", "whitespace-pre");

describe("Truncate (D257)", () => {
  it("cuts an email's muted domain first, then its local part", () => {
    const { container } = render(<Truncate value="alice@corp.example.com" kind="email" />);
    const el = container.querySelector<HTMLElement>("[data-truncate]")!;
    const { head, tail } = parts(el);
    expect(head.textContent).toBe("alice");
    expect(tail.textContent).toBe("@corp.example.com");
    expect(tail).toHaveClass("text-text-muted");
    // The local part's column is sized first; the domain's gets what is left.
    expect(el.className).toContain("grid-cols-[minmax(0,max-content)_minmax(0,1fr)]");
  });

  it("never lets a 60-character local part overflow: it shrinks with an ellipsis too", () => {
    const local = "a".repeat(60);
    const { container } = render(<Truncate value={`${local}@example.com`} kind="email" />);
    const el = container.querySelector<HTMLElement>("[data-truncate]")!;
    expect(el).toHaveClass("max-w-full");
    expect(parts(el).head.textContent).toBe(local);
    cutsBox(parts(el).head);
    cutsBox(parts(el).tail);
    expect(el.className).toContain("minmax(0,max-content)"); // a zero minimum: it can shrink
  });

  it("cuts a name in the middle, keeping its last 8 characters", () => {
    const { container } = render(<Truncate value="m365_management_activity" kind="name" />);
    const el = container.querySelector<HTMLElement>("[data-truncate]")!;
    const { head, tail } = parts(el);
    expect(head.textContent).toBe("m365_management_");
    expect(tail.textContent).toBe("activity");
    cutsBox(head);
    expect(el.className).toContain("grid-cols-[minmax(0,1fr)_minmax(0,max-content)]");
  });

  it("reads a short value whole, as one part", () => {
    const { container } = render(<Truncate value="claude" kind="name" />);
    const el = container.querySelector<HTMLElement>("[data-truncate]")!;
    expect(el.textContent).toBe("claude");
    expect(el.querySelectorAll("[data-part]")).toHaveLength(0);
    expect(el).toHaveClass("[overflow-wrap:anywhere]");
    expect(splitValue("claude", "name")).toEqual(["", "claude"]);
  });

  it.each([
    ["m365_management_activity", "name"],
    ["grace@example.com", "email"],
    ["Office 365 SharePoint Online", "name"],
  ] as const)("gives %s whole as text and title, and hides none of it", (value, kind) => {
    const { container } = render(<Truncate value={value} kind={kind} />);
    const el = container.querySelector<HTMLElement>("[data-truncate]")!;
    expect(el.textContent).toBe(value);
    expect(el).toHaveAttribute("title", value);
    // Read as the text it is: no label on a generic element, nothing hidden.
    expect(el).not.toHaveAttribute("aria-label");
    expect(el.querySelector("[aria-hidden]")).toBeNull();
  });

  it("is a tab stop that shows the whole value on focus as a plain cell, not in a link", () => {
    const { container, rerender } = render(<Truncate value="ws-0042-build" kind="name" />);
    const el = () => container.querySelector<HTMLElement>("[data-truncate]")!;
    expect(el()).toHaveAttribute("tabindex", "0");
    expect(el()).toHaveAttribute("data-full", "ws-0042-build");
    expect(el().className).toContain("after:content-[attr(data-full)");
    expect(el().className).toContain("focus-visible:after:block");
    rerender(
      <a href="#x" title="ws-0042-build">
        <Truncate value="ws-0042-build" kind="name" inLink />
      </a>,
    );
    expect(el()).not.toHaveAttribute("tabindex");
    expect(el()).not.toHaveAttribute("title");
    expect(el()).not.toHaveAttribute("data-full");
  });
});

describe("Copying cut values (lib/copyWhole)", () => {
  it("draws cut values inline for the copy and leaves the clipboard to the browser", () => {
    vi.useFakeTimers();
    try {
      render(<Truncate value="m365_management_activity" kind="name" />);
      installCopyWhole();
      const setData = vi.fn();
      const e = new Event("copy", { bubbles: true, cancelable: true });
      Object.defineProperty(e, "clipboardData", { value: { setData } });
      let during = false;
      const peek = () => (during = document.documentElement.hasAttribute(COPYING));
      document.addEventListener("copy", peek); // runs after the listener
      document.body.dispatchEvent(e);
      document.removeEventListener("copy", peek);
      expect(during).toBe(true);
      expect(e.defaultPrevented).toBe(false);
      expect(setData).not.toHaveBeenCalled();
      vi.runAllTimers();
      expect(document.documentElement.hasAttribute(COPYING)).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("Cutting by character, never inside an emoji (D257)", () => {
  // The eighth UTF-16 unit from the end falls inside the emoji's surrogate pair.
  const name = "build-server-\u{1F680}0042abc";
  it("keeps the emoji whole in Truncate's tail", () => {
    const [head, tail] = splitValue(name, "name");
    expect(head + tail).toBe(name);
    expect(tail).toBe("\u{1F680}0042abc");
    expect(tail).not.toMatch(/[\uD800-\uDFFF]/u); // no half of a pair
  });
  it("keeps the emoji whole in a lane box label", () => {
    const cut = clipMiddle(name, 12);
    expect(cut).toBe("bui…\u{1F680}0042abc");
    expect(cut).not.toMatch(/[\uD800-\uDFFF]/u);
    expect(Array.from(cut)).toHaveLength(12);
  });
});

describe("EntityLink with Truncate", () => {
  it("keeps its href, its link color, and the whole value as its name and title", () => {
    render(<EntityLink kind="user" value="grace@example.com" className="font-mono text-data" />);
    const link = screen.getByRole("link", { name: "grace@example.com" });
    expect(link.getAttribute("href")).toMatch(/user=grace(%40|@)example\.com/);
    expect(link).toHaveAttribute("title", "grace@example.com\nInvestigate this person");
    expect(link).toHaveClass("text-accent-text", "text-data");
    expect(link.querySelector("[data-truncate]")).toHaveAttribute("data-truncate", "email");
    expect(link.textContent).toBe("grace@example.com");
  });

  it("cuts a host in the middle and keeps its label", () => {
    render(<EntityLink kind="host" value="ws-0042" label="build-server-0042.example.internal" />);
    const link = screen.getByRole("link", { name: "build-server-0042.example.internal" });
    expect(link.getAttribute("href")).toContain("host=ws-0042");
    expect(link.querySelector("[data-truncate]")).toHaveAttribute("data-truncate", "name");
    expect(link.querySelector('[data-part="tail"]')?.textContent).toBe("internal");
  });
});

describe("Entity lists (D257)", () => {
  it("keep each comma with the value before it", () => {
    const { container } = render(<EntityList people={["alice", "bob", "carol"]} />);
    const kept = [...container.querySelectorAll(".whitespace-nowrap")];
    expect(kept.map((k) => k.textContent)).toEqual(["alice,", "bob,", "carol"]);
    expect(container.textContent).toBe("alice, bob, carol");
  });
});

describe("A value holding a line break or a tab (D257)", () => {
  it("draws on one line, while its title and name keep it exactly", () => {
    const value = "ws-00\n42\tbuild-host";
    render(<EntityLink kind="host" value={value} />);
    const link = screen.getByRole("link", { name: /^ws-00\s42\sbuild-host$/ });
    expect(link).toHaveAttribute("aria-label", value);
    expect(link).toHaveAttribute("title", `${value}\nInvestigate this machine`);
    // Drawn with spaces in place of the break and the tab; nothing else changes.
    expect(link.textContent).toBe("ws-00 42 build-host");
    expect(link.textContent).toBe(oneLine(value));
  });

  it("keeps a plain cell's focus note on one line too", () => {
    const { container } = render(<Truncate value={"a\nb\tc-host-name-long"} kind="name" />);
    const el = container.querySelector<HTMLElement>("[data-truncate]")!;
    expect(el).toHaveAttribute("data-full", "a b c-host-name-long");
    expect(el).toHaveAttribute("title", "a\nb\tc-host-name-long");
  });
});
