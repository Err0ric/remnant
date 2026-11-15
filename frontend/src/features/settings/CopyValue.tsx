import { useState } from "react";

interface CopyValueProps {
  /** Copied exactly as given. */
  value: string;
}

/** A small Copy link beside a value people paste elsewhere (single sign-on settings). */
export function CopyValue({ value }: CopyValueProps) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard
          ?.writeText(value)
          .then(() => setDone(true))
          .catch(() => setDone(false));
      }}
      className="text-sm text-accent-text hover:underline"
    >
      {done ? "Copied" : "Copy"}
    </button>
  );
}
