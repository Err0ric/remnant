import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ActivityTable } from "@/features/audit/ActivityTable";
import type { AuditEvent } from "@/lib/api";

function row(audit_id: number, action: string, masked: boolean): AuditEvent {
  return {
    audit_id,
    ts: "2026-11-11T10:00:00+00:00",
    user_id: null,
    username: null,
    action,
    outcome: "success",
    ip: null,
    detail: { count: 1, items: ["ChatGPT by a person"] },
    masked,
  };
}

const NOTE = "Names are hidden. An admin can turn on View people in AI usage for you.";

describe("Audit rows with hidden names (D242)", () => {
  it("shows the note once for the page, not per row", () => {
    const rows = [
      row(3, "ai.sighting", true),
      row(2, "ai.sensitive", true),
      row(1, "user.login", false),
    ];
    render(<ActivityTable rows={rows} onUser={() => undefined} />);
    expect(screen.getAllByText(NOTE)).toHaveLength(1);
  });

  it("shows no note when nothing was hidden", () => {
    render(<ActivityTable rows={[row(1, "ai.sighting", false)]} onUser={() => undefined} />);
    expect(screen.queryByText(NOTE)).toBeNull();
  });
});
