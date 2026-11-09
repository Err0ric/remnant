import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AlertItem } from "@/lib/api";
import { DevicePeople } from "@/features/alerts/DevicePeople";
import { GUIDE, guideFor } from "@/features/alerts/guide";

function item(over: Partial<AlertItem>): AlertItem {
  return {
    item_id: "a1", kind: "ai_watch", subject: "service:gemini", ref_id: "service:gemini",
    title: "AI service not approved: Gemini", detail: "", why: "Not approved", count: 0,
    sources: ["dns"], range_start: null, range_end: null,
    created_at: "2026-11-06T10:00:00+00:00", state: "open", closed_at: null, closed_by: null,
    close_reason: null, close_reason_label: null, note: null, resolved: null,
    schedule_id: null, severity: "medium", muted_until: null, history: [], ...over,
  }; // prettier-ignore
}

describe("Why it matters follows the catalog status (owner item 5)", () => {
  it("gives Not approved, Unreviewed, Unknown, and Approved their own wording", () => {
    const text = (s: AlertItem["review_status"]) => guideFor(item({ review_status: s })).why;
    expect(text("not_approved")).toBe(
      "This AI service is marked Not approved, and it is still being used.",
    );
    expect(text("unreviewed")).toBe("An AI service is in use that nobody has reviewed yet.");
    expect(text("unknown")).toContain("not in the AI service catalog");
    expect(text("approved")).toContain("approved after the alert was raised");
    expect(new Set(["not_approved", "unreviewed", "unknown", "approved"].map((s) => text(s as AlertItem["review_status"]))).size).toBe(4); // prettier-ignore
  });

  it("uses the MCP wording for an MCP server and the rule's guide for other alerts", () => {
    const mcp = item({ subject: "mcp:paste-share", review_status: "not_approved" });
    expect(guideFor(mcp).why).toContain("MCP server is marked Not approved");
    const gap = item({ kind: "gap", subject: "dns", review_status: null });
    expect(guideFor(gap)).toBe(GUIDE.gap);
  });
});

describe("Person on device", () => {
  it("names one person with how they were found", () => {
    render(
      <dl>
        <DevicePeople
          found={[{ device: "ws-0101.corp.internal", level: "attributed", people: ["erin@example.com"], count: 1, how: "hooks" }]} // prettier-ignore
        />
      </dl>,
    );
    expect(screen.getByText("Person on device")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "erin@example.com" })).toBeInTheDocument();
    expect(screen.getByText(", seen on this host in the hooks plugin")).toBeInTheDocument();
    expect(screen.queryByText(/Possible/)).toBeNull();
  });

  it("says possible with the count on a shared host and picks nobody", () => {
    render(
      <dl>
        <DevicePeople
          found={[{ device: "ws-0101.corp.internal", level: "possible", people: ["erin@example.com", "frank@example.com"], count: 2, how: "hooks" }]} // prettier-ignore
        />
      </dl>,
    );
    expect(screen.getByText(/Possible:/)).toBeInTheDocument();
    expect(
      screen.getByText(", 2 people seen on this host in the hooks plugin"),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });

  it("shows nothing when no person was found", () => {
    const { container } = render(<dl><DevicePeople found={[]} /></dl>); // prettier-ignore
    expect(container.querySelector("dt")).toBeNull();
  });
});
