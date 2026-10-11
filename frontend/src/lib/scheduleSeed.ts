/**
 * A one-shot handoff into the New schedule form ("Schedule" on Search, a saved search, or a
 * rule run). Kept in memory for this tab and taken once by the Schedules page.
 */
export interface ScheduleSeed {
  kind: "search" | "rule";
  targetId: string;
}

let seed: ScheduleSeed | null = null;

export function seedSchedule(value: ScheduleSeed): void {
  seed = value;
}

export function takeScheduleSeed(): ScheduleSeed | null {
  const value = seed;
  seed = null;
  return value;
}
