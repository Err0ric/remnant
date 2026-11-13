import { cn } from "@/lib/cn";

interface AboutProps {
  text: string;
  /** What the text is, before it: a counting rule by default; "About this" for a note that
   * used to be a line of help text on the page (ADR-0052 section 3.7). */
  lead?: string;
  /** Which edge of the (i) the note opens from: "end" for one near the right of its card. */
  align?: "start" | "end";
}

/** The (i) beside a label: how a number is counted, or a note about the column. The note
 * shows on hover, on keyboard focus (the (i) is a tab stop), and on a tap, and is the (i)'s
 * accessible name for a screen reader. It is drawn from an attribute, so it adds no text to
 * the row or card it sits in. */
export function About({ text, lead = "How this is counted", align = "start" }: AboutProps) {
  const note = `${lead}: ${text}`;
  return (
    <span
      role="img"
      tabIndex={0}
      data-about=""
      data-note={note}
      aria-label={note}
      title={note}
      className={cn(
        "relative flex size-3.5 shrink-0 cursor-help items-center justify-center rounded-full border border-text-muted text-[10px] font-semibold leading-none text-text-muted",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus-ring",
        // The note itself, under the (i).
        "after:pointer-events-none after:absolute after:top-full after:z-40 after:mt-1.5 after:hidden after:w-64 after:whitespace-normal after:rounded-card after:border after:border-border after:bg-surface after:p-2 after:text-left after:text-xs after:font-normal after:leading-snug after:text-text after:shadow-lg after:content-[attr(data-note)]",
        "hover:after:block focus:after:block",
        align === "end" ? "after:right-0" : "after:left-0",
      )}
    >
      i
    </span>
  );
}
