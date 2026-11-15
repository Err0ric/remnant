import { useState } from "react";

interface CopyRawProps {
  /** The stored line, exactly as it is in the lake. */
  raw: string;
}

/** Copies the stored line byte for byte (CLAUDE.md 2.5): line breaks, tabs, and spaces kept.
 * A cut value elsewhere is drawn on one line (D257); this is the exact copy path beside it.
 * "Copied" holds only for the value that was copied, so a new value reads "Copy" again. */
export function CopyRaw({ raw }: CopyRawProps) {
  const [copied, setCopied] = useState<string | null>(null);
  return (
    <button
      type="button"
      aria-label="Copy raw event"
      onClick={() => {
        navigator.clipboard
          ?.writeText(raw)
          .then(() => setCopied(raw))
          .catch(() => setCopied(null));
      }}
      className="ml-auto rounded px-2 py-0.5 text-accent-text hover:bg-surface-head"
    >
      {copied === raw ? "Copied" : "Copy"}
    </button>
  );
}
