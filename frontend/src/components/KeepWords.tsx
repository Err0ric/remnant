import { Fragment } from "react";

/** A word longer than this may still break anywhere (the box's `overflow-wrap`), so one
 * over-long value never overflows its cell. */
export const KEEP_MAX = 48;

/** Ids, addresses, and host names inside a sentence: a word with a hyphen, dot, colon, at,
 * slash, or underscore ("ws-0046", "10.177.0.39", "grace@example.com"). */
const JOINED = /\w[-.:@/_]\w/;

interface KeepWordsProps {
  text: string;
}

/** A sentence that wraps between words only: an id, address, or host name in it is kept on
 * one line ("ws-0046", never "ws-" then "0046"), up to KEEP_MAX characters; one wider than
 * the line is cut with an ellipsis. The text, its copy, and what a screen reader says are
 * unchanged. */
export function KeepWords({ text }: KeepWordsProps) {
  return (
    <>
      {text.split(/(\s+)/).map((part, i) =>
        JOINED.test(part) && part.length <= KEEP_MAX ? (
          // Kept whole, but never wider than its line: a word that cannot fit is cut with
          // an ellipsis (the full title is on the link's hover), never clipped unmarked.
          <span key={i} data-keep="" className="inline-block max-w-full truncate align-top">
            {part}
          </span>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}
