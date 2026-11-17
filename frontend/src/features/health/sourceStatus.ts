import { localStamp } from "@/lib/localTime";
import type { Overview, Source } from "@/lib/api";
import { heldText } from "@/features/sources/VendorAlertNotify";
import { idleText, quietFrom, quietWord, shownGaps } from "./flow";

export type StatusLevel = "unhealthy" | "attention" | "paused" | "healthy";

/** A source's status as every page says it (fix list 2026-11-16 item 19): the level and
 * word come from the server's one condition (`condition`, `problem`, `idle` on each
 * Overview source, `app.search.source_state`); the reader's own facts only give the
 * sentence. Health and Settings > Sources both draw it with `SourceStatusLabel`. */
export interface SourceStatusView {
  level: StatusLevel;
  /** "Flowing", "Idle", "Quiet 5 d", "Never sent", "Gap", "Needs attention", "Unhealthy",
   * "Paused". */
  word: string;
  reason: string | null;
  /** The reason is only the quiet sentence, left out under a gap's own sentence (D255). */
  quietNote?: boolean;
}

type Judged = Overview["sources"][number];

const WORD: Record<StatusLevel, string> = {
  unhealthy: "Unhealthy",
  attention: "Needs attention",
  paused: "Paused",
  healthy: "Flowing",
};

function human(seconds: number): string {
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h`;
  return `${Math.round(seconds / 86400)} d`;
}

/** What the reader says before the server has judged the source (the Overview loading):
 * the level and the sentence from its reading status alone. */
function fromReader(s: Source): SourceStatusView {
  const st = s.status;
  const v = (level: StatusLevel, reason: string | null, quietNote?: boolean) => ({
    level,
    word: WORD[level],
    reason,
    quietNote,
  });
  if (!s.enabled || st.state === "disabled") return v("paused", "Turned off");
  if (st.state === "error") return v("unhealthy", st.error);
  if (s.quiet?.state === "quiet")
    return v("unhealthy", `No events for over ${human(s.quiet.quiet_after_s)}`, true);
  if (s.alert_pause)
    return v(
      "attention",
      `Over 100 new alerts an hour: below High stored, not raised (${heldText(s.alert_pause)})`,
    );
  if (st.warnings?.length) return v("attention", st.warnings.join("; "));
  if (st.retry_at) return v("attention", `Retrying at ${localStamp(st.retry_at)}`);
  if (st.time_offset_text) return v("attention", st.time_offset_text);
  if ((st.behind_s ?? 0) > 3600)
    return v("attention", `Reading is ${human(st.behind_s ?? 0)} behind`);
  if (st.records_skipped) return v("attention", `${st.records_skipped} records could not be read`);
  if (st.files_waiting) return v("attention", `${st.files_waiting} files still being written`);
  if (st.state === "waiting") return v("attention", "Not read yet");
  return v("healthy", null);
}

/** What the reader alone says, for Health's rows while the Overview loads (as Health did
 * before item 19). Never a status on Settings or the Dashboard. */
export function readerStatus(s: Source): SourceStatusView {
  return fromReader(s);
}

/** The one status of a source: `h` is its Overview row, `now` the Overview's time. A reader
 * that stopped on an error is "Unhealthy" at once, whatever an older Overview says (the
 * server's rule: an error is always unhealthy), so green never shows over an error. Without
 * the Overview the status is not known: null, never derived from the reader. */
export function sourceStatus(
  s: Source | undefined,
  h: Judged | undefined,
  now: string | undefined,
): SourceStatusView | null {
  const r: SourceStatusView = s
    ? fromReader(s)
    : { level: "healthy", word: WORD.healthy, reason: null };
  if (s && s.enabled && s.status.state === "error")
    return { ...r, level: "unhealthy", word: WORD.unhealthy };
  if (!h || !now) return null;
  switch (h.condition) {
    case "paused":
      return { ...r, level: "paused", word: WORD.paused, reason: r.reason ?? "Turned off" };
    case "error":
      return { ...r, level: "unhealthy", word: WORD.unhealthy };
    case "quiet": {
      const word = quietWord(quietFrom(h), now);
      // The server's one rule for a source problem (item 12): the rail counts the same.
      return {
        ...r,
        level: h.problem ?? "attention",
        word: word.charAt(0).toUpperCase() + word.slice(1),
      };
    }
    case "gap":
      return { ...r, level: "attention", word: "Gap" };
    case "attention":
      return {
        ...r,
        level: "attention",
        word: WORD.attention,
        reason: r.reason ?? "Needs a look",
      };
    default:
      // Marked "Quiet is normal" and silent inside its days (D260): healthy, said in a word.
      return h.idle
        ? { level: "healthy", word: "Idle", reason: idleText(quietFrom(h), now) }
        : { level: "healthy", word: WORD.healthy, reason: null };
  }
}

/** Drawn greyed: only quiet (no gap hours shown, not in error), or idle (D255, D260). */
export function greyedStatus<G>(h: Judged | undefined, gaps: G[] | undefined): boolean {
  return (shownGaps(h, gaps).length === 0 && h?.condition === "quiet") || Boolean(h?.idle);
}
