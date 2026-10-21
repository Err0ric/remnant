import { useState } from "react";
import type { FirstAdminLink } from "./firstAdminLink";

interface FirstAdminLinkPanelProps {
  value: FirstAdminLink;
  onDone: () => void;
}

/** Shown on sign-in right after the first administrator is invited from open mode. */
export function FirstAdminLinkPanel({ value, onDone }: FirstAdminLinkPanelProps) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value.link);
      setCopied(true);
    } catch {
      setCopied(false); // the field stays selectable for manual copy
    }
  };
  return (
    <section
      aria-label="Administrator invite link"
      className="mb-4 rounded-card border border-accent bg-accent-subtle p-4"
    >
      <h2 className="text-base font-semibold">Administrator invite link</h2>
      <p className="mt-1 text-sm text-text-secondary">
        The account <span className="font-semibold text-text">{value.username}</span> was created,
        so this install now requires sign-in. Open this link to set its password. It works once,
        expires in 24 hours, and is not shown again.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <input
          readOnly
          aria-label="One-time link"
          value={value.link}
          onFocus={(e) => e.currentTarget.select()}
          className="h-8 min-w-0 flex-1 rounded border border-border-strong bg-inset px-2 font-mono text-sm text-text"
        />
        <button
          type="button"
          onClick={() => void copy()}
          className="h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head"
        >
          {copied ? "Copied" : "Copy"}
        </button>
        <a
          href={value.link}
          className="flex h-8 items-center rounded bg-accent px-3 text-sm font-semibold text-white no-underline hover:brightness-110"
        >
          Open link
        </a>
        <button
          type="button"
          onClick={onDone}
          className="h-8 px-2 text-sm text-text-secondary hover:text-text"
        >
          Hide
        </button>
      </div>
    </section>
  );
}
