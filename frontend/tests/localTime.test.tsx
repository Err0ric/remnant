import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { When } from "@/components/When";
import { localClock, localDate, repeatsLocalHour } from "@/lib/localTime";

const LA = "America/Los_Angeles";
// 2026-11-01: 01:00 to 01:59 happens twice in Los Angeles (PDT, then PST).
const FIRST = new Date("2026-11-01T08:15:00Z");
const SECOND = new Date("2026-11-01T09:15:00Z");

describe("times around a clock change (owner, 2026-11-01)", () => {
  it("tells the two readings of a repeated hour apart", () => {
    expect(repeatsLocalHour(FIRST, LA)).toBe(true);
    expect(repeatsLocalHour(SECOND, LA)).toBe(true);
    expect(localClock(FIRST, LA)).toBe("01:15 PDT");
    expect(localClock(SECOND, LA)).toBe("01:15 PST");
  });

  it("adds nothing on an ordinary hour or in UTC", () => {
    expect(localClock(new Date("2026-11-01T11:15:00Z"), LA)).toBe("03:15");
    expect(localClock(FIRST, "UTC")).toBe("08:15");
    expect(localClock(new Date("2026-03-08T10:30:00Z"), LA)).toBe("03:30");
  });

  it("groups by the viewer's day", () => {
    expect(localDate(new Date("2026-11-01T06:30:00Z"), LA)).toBe("2026-10-31");
    expect(localDate(FIRST, LA)).toBe("2026-11-01");
  });

  it("shows the zone in tables only when the hour repeats", () => {
    render(
      <>
        <When iso={FIRST.toISOString()} timeZone={LA} />
        <When iso={SECOND.toISOString()} timeZone={LA} />
        <When iso="2026-11-01T11:15:00Z" timeZone={LA} />
      </>,
    );
    expect(screen.getByText(/Nov 1, 1:15 AM\s*PDT/)).toBeVisible();
    expect(screen.getByText(/Nov 1, 1:15 AM\s*PST/)).toBeVisible();
    expect(screen.getByText("Nov 1, 3:15 AM")).toBeVisible();
  });
});
