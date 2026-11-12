import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FollowsRow } from "@/features/alerts/FollowsRow";

describe("An alert that follows a closed one (ADR-0049 0c)", () => {
  it("links to the earlier, closed alert", () => {
    render(
      <dl>
        <FollowsRow follows="item-1" />
      </dl>,
    );
    expect(screen.getByText("Follows")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Earlier alert, closed before this one rose" });
    expect(link.getAttribute("href")).toContain("#item=item-1");
  });

  it("shows nothing for an alert that follows none", () => {
    render(
      <dl>
        <FollowsRow follows={null} />
      </dl>,
    );
    expect(screen.queryByText("Follows")).toBeNull();
  });
});
