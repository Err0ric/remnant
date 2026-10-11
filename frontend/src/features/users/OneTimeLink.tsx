import { useState } from "react";

interface OneTimeLinkProps {
  title: string;
  username: string;
  link: string;
  onDone: () => void;
}

/** Shows an invite or reset link exactly once, with copy and a clear warning. */
export function OneTimeLink({ title, username, link, onDone }: OneTimeLinkProps) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
    } catch {
      setCopied(false); // the field stays selectable for manual copy
    }
  };
  return (
    <section aria-label={title} className="rounded-card border border-accent bg-accent-subtle p-4">
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="mt-1 text-sm text-text-secondary">
        Send this to <span className="font-semibold text-text">{username}</span> through a channel
        you trust. It works once, expires in 24 hours, and is not shown again.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <input
          readOnly
          aria-label="One-time link"
          value={link}
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
        <button
          type="button"
          onClick={onDone}
          className="h-8 rounded bg-accent px-3 text-sm font-semibold text-white hover:brightness-110"
        >
          Done
        </button>
      </div>
    </section>
  );
}
