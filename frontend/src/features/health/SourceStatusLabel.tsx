import type { StatusLevel } from "./sourceStatus";

const DOT: Record<StatusLevel, string> = {
  unhealthy: "bg-danger",
  attention: "bg-warn",
  paused: "bg-text-muted",
  healthy: "bg-ok",
  // Neutral and apart from the grey of quiet or never sent: a ring, no fill (SPEC 3.5).
  shared: "border border-text-secondary bg-transparent",
};

interface SourceStatusLabelProps {
  level: StatusLevel;
  word: string;
  /** Only quiet or idle: the dot in `--text-muted` (D255). */
  greyed?: boolean;
}

/** A source's status as a dot and a word, the same on Health and Settings > Sources
 * (`sourceStatus`). Never color alone (DESIGN.md). */
export function SourceStatusLabel({ level, word, greyed = false }: SourceStatusLabelProps) {
  return (
    <span className="flex min-w-0 items-center gap-1.5 whitespace-nowrap text-text-secondary">
      <span
        aria-hidden
        data-dot=""
        className={`inline-block size-2 shrink-0 rounded-full ${greyed ? "bg-text-muted" : DOT[level]}`}
      />
      <span className="truncate" data-status-word="" title={word}>
        {word}
      </span>
    </span>
  );
}
