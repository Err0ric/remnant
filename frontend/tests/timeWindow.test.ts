import { describe, expect, it } from "vitest";
import { lastDays, localInput, localTime, TIME_IDS, utcText, windowOf } from "@/lib/timeWindow";

const now = new Date("2026-11-13T12:00:00Z");

describe("A page's time window (ADR-0052 section 3.7; owner, 2026-11-13)", () => {
  it("has the five choices, in order", () => {
    expect(TIME_IDS).toEqual(["1h", "24h", "7d", "30d", "custom"]);
  });

  it("ends now for a preset and is open-ended", () => {
    expect(windowOf({ preset: "1h", from: "", to: "" }, now)).toEqual({
      from: new Date("2026-11-13T11:00:00Z"),
      to: null,
    });
    expect(windowOf({ preset: "30d", from: "x", to: "y" }, now).from).toEqual(
      new Date("2026-10-14T12:00:00Z"),
    );
  });

  it("takes Custom from the two local date-times; an empty side is open", () => {
    const w = windowOf({ preset: "custom", from: "2026-11-01T08:00", to: "" }, now);
    expect(w.from).toEqual(new Date("2026-11-01T08:00"));
    expect(w.to).toBeNull();
    expect(windowOf({ preset: "custom", from: "", to: "" }, now)).toEqual({ from: null, to: null });
  });

  it("reads nothing from a value that is not a date-time", () => {
    expect(localTime("yesterday")).toBeNull();
    expect(localTime("2026-13-45T99:99")).toBeNull();
    expect(utcText("")).toBe("");
    expect(utcText("2026-11-01T08:00")).toMatch(/^2026-1[01]-\d\d \d\d:\d\d UTC$/);
  });

  it("includes the whole minute the end names, or the second when one is given", () => {
    const end = (to: string) => windowOf({ preset: "custom", from: "", to }, now).to?.getTime();
    expect(end("2026-10-22T07:30")).toBe(new Date("2026-10-22T07:30:59.999").getTime());
    expect(end("2026-10-22T07:30:10")).toBe(new Date("2026-10-22T07:30:10.999").getTime());
    expect(end("")).toBeUndefined();
  });

  it("shows a moment as a local date-time value and reads it back as the same moment", () => {
    const iso = "2026-11-06T08:00:07.000Z";
    const shown = localInput(iso);
    expect(shown).toMatch(/^2026-11-0[567]T\d\d:\d\d:07$/);
    expect(localTime(shown)?.toISOString()).toBe(iso);
    // Whole minutes show no seconds.
    expect(localInput("2026-11-06T08:00:00Z")).toMatch(/^2026-11-0[567]T\d\d:\d\d$/);
    expect(localInput("not a time")).toBe("");
  });

  it("labels a panel that counts whole days back from now", () => {
    expect(lastDays(1)).toBe("Last 24 hours");
    expect(lastDays(7)).toBe("Last 7 days");
    expect(lastDays(30)).toBe("Last 30 days");
  });
});
