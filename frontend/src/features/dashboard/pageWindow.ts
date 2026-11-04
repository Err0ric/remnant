import type { PageWindow } from "@/lib/api";

// One time window for the whole Dashboard (ADR-0038 edit 10): AI Watch and the sections
// follow it. Remembered in this browser.
export const WINDOWS: { id: PageWindow; label: string; days: number }[] = [
  { id: "24h", label: "24 hours", days: 1 },
  { id: "7d", label: "7 days", days: 7 },
  { id: "30d", label: "30 days", days: 30 },
];

const KEY = "dashboard.window";

export function readWindow(): PageWindow {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "24h" || v === "7d" || v === "30d" ? v : "7d";
  } catch {
    return "7d";
  }
}

export function saveWindow(w: PageWindow): void {
  try {
    window.localStorage.setItem(KEY, w);
  } catch {
    // Storage blocked: the window still applies for this page view.
  }
}

export function daysOf(w: PageWindow): number {
  return WINDOWS.find((x) => x.id === w)?.days ?? 7;
}

/** What a trend's dashed line is (owner, 2026-11-03): each point compared with the same
 * point one window earlier, not an average of the window before. */
export function comparisonLabel(w: PageWindow): string {
  if (w === "24h") return "Same hour yesterday";
  if (w === "7d") return "Same hour last week";
  return `Same day ${daysOf(w)} days earlier`;
}

/** The comparison point's time: the same point one window earlier. */
export function comparisonTime(w: PageWindow, at: Date): Date {
  const d = new Date(at.getTime());
  d.setDate(d.getDate() - daysOf(w)); // calendar days, so a clock change keeps the hour
  return d;
}

/** "the previous 7 days", "the previous 24 hours". */
export function previousPhrase(w: PageWindow): string {
  return w === "24h" ? "the previous 24 hours" : `the previous ${daysOf(w)} days`;
}

const fmt = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });

/** "Oct 24 to Oct 30" (days), or "Oct 29, 12 PM to Oct 30, 11 AM" (24 hours), in the viewer's time zone. */
export function rangeText(w: PageWindow, now: Date = new Date()): string {
  if (w === "24h") {
    const from = new Date(now.getTime() - 86_400_000);
    const t = (d: Date) => `${fmt(d)}, ${d.toLocaleTimeString("en-US", { hour: "numeric" })}`;
    return `${t(from)} to ${t(now)}`;
  }
  const from = new Date(now.getTime() - (daysOf(w) - 1) * 86_400_000);
  return `${fmt(from)} to ${fmt(now)}`;
}
