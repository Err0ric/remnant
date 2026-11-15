/** A cut value (`components/Truncate`) is two parts in a grid row. A browser copies them
 * as two lines, and leaves out a part cut to nothing. One document-level `copy` listener
 * sets the attribute below for the length of the copy: every cut value is then drawn as
 * plain inline text (styles/globals.css), so the browser's own copy, plain text and HTML
 * alike, has each value whole and on one line, for a selection of any size (D257). The
 * listener writes no clipboard data and never cancels the copy. */

export const COPYING = "data-copying";

export function onCopy() {
  const root = document.documentElement;
  root.setAttribute(COPYING, "");
  // The browser serializes the selection after the event's listeners, with styles as they
  // are then; reading layout here applies the attribute before it does.
  void root.offsetWidth;
  setTimeout(() => root.removeAttribute(COPYING), 0);
}

let installed = false;

/** Installed once, from the app's entry point. */
export function installCopyWhole() {
  if (installed) return;
  installed = true;
  document.addEventListener("copy", onCopy);
}
