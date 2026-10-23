import type { SourceGap } from "@/lib/api";
import { navigate, pathFor } from "@/lib/route";
import { gapText } from "./flow";

interface GapNoteProps {
  sourceId: string;
  gaps: SourceGap[];
  now: string;
}

/** The same gap sentence Health shows, wherever a source is listed (F61, ADR-0037 row 12):
 * Settings > Sources no longer disagrees with Health. Links back to the Health row. */
export function GapNote({ sourceId, gaps, now }: GapNoteProps) {
  if (!gaps.length) return null;
  const section = `source=${encodeURIComponent(sourceId)}`;
  return (
    <div className="text-sm text-warn">
      {gaps.map((g) => (
        <p key={g.start}>{gapText(g, now)}</p>
      ))}
      <a
        href={`${pathFor("health")}#${section}`}
        onClick={(e) => {
          if (e.metaKey || e.ctrlKey || e.shiftKey) return;
          e.preventDefault();
          navigate("health", section);
        }}
        className="text-accent-text hover:underline"
      >
        Show on Health
      </a>
    </div>
  );
}
