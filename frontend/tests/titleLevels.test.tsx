import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SectionTitle } from "@/components/SectionTitle";
import { PanelTitle } from "@/components/PanelTitle";

describe("title levels (DESIGN.md 7)", () => {
  it("renders a section title as a heading on its slate pill, never as a link", () => {
    render(<SectionTitle>AI Watch</SectionTitle>);
    const h = screen.getByRole("heading", { level: 2, name: "AI Watch" });
    expect(h.dataset.title).toBe("section");
    expect(h.className).toContain("bg-section-bg");
    expect(h.className).toContain("text-section-text");
    expect(h.className).not.toMatch(/accent|hover:|underline|cursor-pointer/);
  });

  it("renders a panel title in small upper case, below a section title, never as a link", () => {
    render(
      <>
        <PanelTitle>Top services</PanelTitle>
        <PanelTitle as="span">Failed sign-ins</PanelTitle>
      </>,
    );
    const h = screen.getByRole("heading", { level: 3, name: "Top services" });
    expect(h.dataset.title).toBe("panel");
    expect(h.className).toMatch(/text-xs/);
    expect(h.className).toMatch(/uppercase/);
    expect(h.className).toContain("text-panel-title");
    expect(h.className).not.toMatch(/accent|hover:|underline|cursor-pointer/);
    expect(screen.getByText("Failed sign-ins").tagName).toBe("SPAN");
  });
});
