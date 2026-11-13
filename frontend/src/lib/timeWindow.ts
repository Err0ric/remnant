import type { TimePreset } from "@/components/FilterBar";

/** A page's time filter: one of the four fixed windows ending now, or Custom with a start
 * and an end the person picked. Custom values are local date-times as a `datetime-local`
 * input gives them ("2026-11-12T08:00"); an empty one leaves that side open, so Custom
 * also covers "everything kept" (ADR-0052 section 3.7; owner, 2026-11-13). */
export interface TimeChoice {
  preset: TimePreset;
  from: string;
  to: string;
}

const SPAN_MS: Record<Exclude<TimePreset, "custom">, number> = {
  "1h": 3_600_000,
  "24h": 86_400_000,
  "7d": 7 * 86_400_000,
  "30d": 30 * 86_400_000,
};

export const TIME_IDS: readonly TimePreset[] = ["1h", "24h", "7d", "30d", "custom"];

const LOCAL = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/;

/** A `datetime-local` value as a time, in the viewer's time zone; null when empty or not one. */
export function localTime(value: string): Date | null {
  if (!LOCAL.test(value)) return null;
  const at = new Date(value);
  return Number.isNaN(at.getTime()) ? null : at;
}

/** The window a choice stands for. A null side is open. */
export function windowOf(
  choice: TimeChoice,
  now: Date = new Date(),
): { from: Date | null; to: Date | null } {
  if (choice.preset === "custom") {
    // The end includes the minute (or second) it names: "to 07:30" keeps 07:30:20.
    const to = localTime(choice.to);
    const whole = to ? (choice.to.length > 16 ? 999 : 59_999) : 0;
    return { from: localTime(choice.from), to: to ? new Date(to.getTime() + whole) : null };
  }
  return { from: new Date(now.getTime() - SPAN_MS[choice.preset]), to: null };
}

/** "2026-11-12 16:00 UTC" for a local date-time value: what the hover says. */
export function utcText(value: string): string {
  const at = localTime(value);
  return at ? `${at.toISOString().slice(0, 16).replace("T", " ")} UTC` : "";
}

/** An ISO time as a `datetime-local` value in the viewer's time zone, to the second (the
 * seconds are left out when zero): what Custom shows for a window another page handed over. */
export function localInput(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  const day = `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`;
  const clock = `${pad(at.getHours())}:${pad(at.getMinutes())}`;
  return `${day}T${clock}${at.getSeconds() ? `:${pad(at.getSeconds())}` : ""}`;
}

/** "Last 7 days", "Last 24 hours": the label of a panel that counts whole days back from
 * now, whatever the page's time choice is (owner, 2026-11-13). */
export function lastDays(days: number): string {
  return days === 1 ? "Last 24 hours" : `Last ${days} days`;
}
