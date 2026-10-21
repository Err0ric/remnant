/** "4 min ago" style age of `stamp` relative to `now`, both ISO strings. */
export function since(stamp: string, now: string): string {
  const s = Math.max(0, (Date.parse(now) - Date.parse(stamp)) / 1000);
  if (Number.isNaN(s)) return "";
  if (s < 90) return "just now";
  if (s < 90 * 60) return `${Math.round(s / 60)} min ago`;
  if (s < 36 * 3600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

/** "2026-10-10 12:00" in UTC, as the rest of the app shows times. */
export function stamp(iso: string): string {
  return iso.slice(0, 16).replace("T", " ");
}

/** "Oct 17 14:00 to 15:00 UTC": one hour bucket, from its start (ISO). */
export function hourLabel(start: string): string {
  const d = new Date(start);
  if (Number.isNaN(d.getTime())) return start;
  const day = d.toLocaleString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  const h = d.getUTCHours();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${day} ${pad(h)}:00 to ${pad((h + 1) % 24)}:00 UTC`;
}
