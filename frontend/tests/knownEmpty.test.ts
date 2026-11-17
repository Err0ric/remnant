import { describe, expect, it } from "vitest";
import type { Overview } from "@/lib/api";
import { knownEmpty, windowStarts } from "@/features/dashboard/shape";

const NOW = new Date("2026-11-17T06:30:00Z");
const file = (id: string) => ({ source_id: id, kind: "file" as const, template_id: id });
const m365 = { source_id: "m365_signin", kind: "m365" as const, template_id: "m365_signin" };

function overview(extra: Partial<Overview>, newest: Record<string, string | null>): Overview {
  return {
    sources: Object.entries(newest).map(([source_id, t]) => ({
      source_id,
      newest_event_at: t,
      last_event_at: t,
    })),
    ...extra,
  } as unknown as Overview;
}

describe("what the Dashboard knows is empty before its sections answer (item 27)", () => {
  it("starts the 24 hour window at the hour 23 hours back, the window before a day earlier", () => {
    const { start, before } = windowStarts("24h", NOW);
    expect(start.toISOString()).toBe("2026-11-16T07:00:00.000Z");
    expect(before.toISOString()).toBe("2026-11-15T07:00:00.000Z");
  });

  it("calls Detections empty only with no rule on and no match since the window before", () => {
    const none = overview({ rules_enabled: 0, rules_last_match: null }, {});
    expect(knownEmpty("7d", [], none, NOW).detections).toBe(true);
    const old = overview({ rules_enabled: 0, rules_last_match: "2026-09-01 10:00:00" }, {});
    expect(knownEmpty("7d", [], old, NOW).detections).toBe(true);
    const recent = overview({ rules_enabled: 0, rules_last_match: "2026-11-16 10:00:00" }, {});
    expect(knownEmpty("7d", [], recent, NOW).detections).toBe(false);
    expect(knownEmpty("7d", [], overview({ rules_enabled: 2 }, {}), NOW).detections).toBe(false);
    // Without the Overview nothing is known.
    expect(knownEmpty("7d", [], undefined, NOW).detections).toBe(false);
  });

  it("calls Attacks and access empty when every source it counts went quiet before the window", () => {
    const quiet = overview(
      {},
      { lin_auth: "2026-11-15T16:15:00Z", dns: null, m365_signin: NOW.toISOString() },
    );
    const sources = [file("lin_auth"), file("dns"), m365];
    // The Microsoft 365 source is not one Attacks and access counts.
    expect(knownEmpty("24h", sources, quiet, NOW).attacks).toBe(true);
    expect(knownEmpty("7d", sources, quiet, NOW).attacks).toBe(false);
    const fresh = overview({}, { lin_auth: "2026-11-17T05:00:00Z", dns: null });
    expect(knownEmpty("24h", sources, fresh, NOW).attacks).toBe(false);
    // A source the Overview does not list is not known to be quiet.
    expect(knownEmpty("24h", [file("lin_auth"), file("vpn")], quiet, NOW).attacks).toBe(false);
  });
});
