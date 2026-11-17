import type { StatusLevel } from "./sourceStatus";

const DOT: Record<StatusLevel, string> = {
  unhealthy: "bg-danger",
  attention: "bg-warn",
  paused: "bg-text-muted",
  healthy: "bg-ok",
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
      <span className="truncate" data-status-word="">
        {word}
      </span>
    </span>
  );
}
