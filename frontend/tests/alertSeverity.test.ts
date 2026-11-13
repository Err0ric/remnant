import { describe, expect, it } from "vitest";
import type { AlertItem, AlertList } from "@/lib/api";
import { needsYouRows } from "@/features/dashboard/NeedsYou";

function item(over: Partial<AlertItem>): AlertItem {
  return {
    item_id: "a1",
    kind: "gap",
    subject: "lin_auth",
    ref_id: null,
    title: "lin_auth stopped sending",
    detail: "No events received for 4 d",
    why: null,
    count: null,
    sources: ["lin_auth"],
    range_start: null,
    range_end: null,
    created_at: "2026-11-06T10:00:00+00:00",
    state: "open",
    closed_at: null,
    closed_by: null,
    close_reason: null,
    close_reason_label: null,
    note: null,
    resolved: null,
    schedule_id: null,
    severity: "medium",
    muted_until: null,
    history: [],
    ...over,
  };
}

function list(items: AlertItem[]): AlertList {
  return {
    items,
    open: items.length,
    restricted: false,
    muted: 0,
    reasons: {} as AlertList["reasons"],
  };
}

describe("one severity per alert (review item 2)", () => {
  it("Needs you shows the stored severity, and never gives a source gap one", () => {
    const rows = needsYouRows(
      list([
        item({ item_id: "g1", subject: "lin_auth", severity: "medium" }),
        item({ item_id: "r1", kind: "rule", subject: "rule-1", severity: "medium" }),
        item({ item_id: "r2", kind: "rule", subject: "rule-2", severity: null }),
        item({ item_id: "w1", kind: "ai_watch", subject: "service:x", severity: "high" }),
      ]),
      [],
      undefined,
    );
    const by = Object.fromEntries(rows.map((r) => [r.key, [r.severity, r.order]]));
    // A gap alert is a blind row (ADR-0052 3.9): pinned first, with no severity.
    expect(by["gap:g1"]).toEqual([null, 1]);
    expect(by["alert:w1"]).toEqual(["high", 2]);
    expect(by["alert:r1"]).toEqual(["medium", 3]);
    expect(by["alert:r2"]).toEqual([null, 3]);
    expect(rows[0]?.key).toBe("gap:g1");
    expect(rows[1]?.key).toBe("alert:w1");
  });
});
