import { cn } from "@/lib/cn";

/** The characters a middle cut keeps at the end of a name. */
export const TAIL = 8;

interface TruncateProps {
  value: string;
  /** `email`: the muted "@domain" is cut first, then the local part. `name` (source ids,
   * hosts, apps, networks, file names): cut in the middle, keeping the last 8 characters
   * until there is no room even for those. Sentences never use this; they wrap instead. */
  kind: "email" | "name";
  /** Inside a link or button, which then carries the title and the accessible name (the
   * full value): not a tab stop, no tooltip of its own. */
  inLink?: boolean;
  className?: string;
}

const segmenter =
  typeof Intl !== "undefined" && "Segmenter" in Intl
    ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
    : null;

/** A value as the characters a reader sees (graphemes where the browser can tell them,
 * code points otherwise), so a cut never splits an emoji or an accent from its letter. */
export function characters(value: string): string[] {
  return segmenter ? Array.from(segmenter.segment(value), (s) => s.segment) : Array.from(value);
}

/** The two parts of a value: the one cut first, and the one kept longest. */
export function splitValue(value: string, kind: TruncateProps["kind"]): [string, string] {
  if (kind === "email") {
    const at = value.indexOf("@");
    return at > 0 ? [value.slice(0, at), value.slice(at)] : [value, ""];
  }
  const chars = characters(value);
  return chars.length > TAIL
    ? [chars.slice(0, -TAIL).join(""), chars.slice(-TAIL).join("")]
    : ["", value];
}

const PART = "min-w-0 overflow-hidden text-ellipsis whitespace-pre";

/** One line, always: a line break or tab in an untrusted value is drawn as a space, while
 * spaces stay as they are (a part may start with one). Only the drawing: the title and the
 * names around it keep the value exactly. */
export const oneLine = (text: string) => text.replace(/[\n\r\t\f\v\u2028\u2029]/g, " ");

/** A long identity cut where it hurts least (DESIGN.md section 7, D257), in CSS only: two
 * parts in one grid row. The kept part's column is `minmax(0, max-content)`, sized first;
 * the cut part's is `minmax(0, 1fr)` and gets what is left, so it shrinks first and the
 * kept part shrinks only when the other is gone. Nothing overflows its box, and a column
 * of an auto-width table can still shrink. The text of the two parts is the value (a line
 * break or tab drawn as a space);
 * `lib/copyWhole` removes the line break a browser copies between them. A plain cell is a
 * tab stop that shows the whole value on focus, drawn from an attribute (as `About`). */
export function Truncate({ value, kind, inLink = false, className }: TruncateProps) {
  const [head, tail] = splitValue(value, kind);
  const keepHead = kind === "email";
  const focus = inLink
    ? undefined
    : cn(
        "relative rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus-ring",
        // The whole value under the cell while it has keyboard focus; never read twice.
        "after:pointer-events-none after:absolute after:left-0 after:top-full after:z-40 after:mt-1 after:hidden after:whitespace-pre after:rounded-card after:border after:border-border after:bg-surface after:px-2 after:py-1 after:text-text after:shadow-lg after:content-[attr(data-full)_/_''] focus-visible:after:block",
      );
  const common = {
    "data-truncate": kind,
    "data-full": inLink ? undefined : oneLine(value),
    title: inLink ? undefined : value,
    tabIndex: inLink ? undefined : 0,
  };
  // A short name (8 characters at most) or an email with no "@" is one part: plain text
  // that may wrap anywhere, so it never overflows and copies as it is.
  if (!head || !tail)
    return (
      <span {...common} className={cn("[overflow-wrap:anywhere]", focus, className)}>
        {value}
      </span>
    );
  return (
    <span
      {...common}
      className={cn(
        // One row, always: the parts flow into columns, so no browser ever stacks the head
        // over the tail ("clau" over "de_hooks", fix list item 10).
        "inline-grid max-w-full grid-flow-col align-bottom",
        keepHead
          ? "grid-cols-[minmax(0,max-content)_minmax(0,1fr)]"
          : "grid-cols-[minmax(0,1fr)_minmax(0,max-content)]",
        focus,
        className,
      )}
    >
      <span data-part="head" className={PART}>
        {oneLine(head)}
      </span>
      <span data-part="tail" className={cn(PART, keepHead && "text-text-muted")}>
        {oneLine(tail)}
      </span>
    </span>
  );
}
