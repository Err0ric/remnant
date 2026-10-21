import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "@/components/ErrorBoundary";

function Broken(): JSX.Element {
  throw new Error("bad record");
}

describe("ErrorBoundary", () => {
  it("shows a note instead of blanking the app when a part throws", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <div>
        <p>Still here</p>
        <ErrorBoundary label="This tab">
          <Broken />
        </ErrorBoundary>
      </div>,
    );
    expect(screen.getByText("Still here")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("This tab could not be shown");
  });
});
