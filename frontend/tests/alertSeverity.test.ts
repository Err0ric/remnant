import { describe, expect, it } from "vitest";
import type { AlertItem, AlertList } from "@/lib/api";
import { attentionLines } from "@/features/dashboard/Attention";
import { summarize } from "@/features/alerts/guide";

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
    restricted: 0,
    muted: 0,
    reasons: {} as AlertList["reasons"],
  };
}

describe("one severity per alert (review item 2)", () => {
  it("Needs attention shows the stored severity, not one derived from the kind", () => {
    const lines = attentionLines(
      list([
        item({ item_id: "g1", subject: "lin_auth", severity: "medium" }),
        item({ item_id: "g2", subject: "win_dc", severity: null }),
        item({ item_id: "w1", kind: "ai_watch", subject: "service:x", severity: "high" }),
      ]),
      [],
    );
    const by = Object.fromEntries(lines.map((l) => [l.key, [l.badge, l.tone]]));
    expect(by["a:g1"]).toEqual(["Medium", "medium"]);
    expect(by["a:g2"]).toEqual(["", "none"]);
    expect(by["a:w1"]).toEqual(["High", "high"]);
    expect(lines.map((l) => l.key)).toEqual(["a:w1", "a:g1", "a:g2"]);
  });

  it("the strip shows the counts it is given", () => {
    const items = [item({ severity: "medium" }), item({ item_id: "a2", severity: "medium" })];
    expect(summarize(items).medium).toBe(2);
    const s = summarize(items, new Date(), { high: 0, medium: 5, other: 1 });
    expect([s.high, s.medium, s.other]).toEqual([0, 5, 1]);
  });
});
