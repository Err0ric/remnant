import { useState } from "react";

interface SigningKeyProps {
  name: string;
  signingKey: string;
  onDone: () => void;
}

/** A webhook's signing key, shown once after it is made (ADR-0007 row 5). */
export function SigningKey({ name, signingKey, onDone }: SigningKeyProps) {
  const [copied, setCopied] = useState(false);
  return (
    <section
      aria-label="Signing key"
      className="rounded-card border border-accent bg-accent-subtle p-4 text-sm"
    >
      <h2 className="text-base font-semibold">Signing key for {name}</h2>
      <p className="mt-1 text-text-secondary">
        Give this to the receiving service so it can check the{" "}
        <span className="font-mono">X-Signature-256</span> header (HMAC-SHA256 of{" "}
        <span className="font-mono">timestamp.body</span>). It is not shown again.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <input
          readOnly
          aria-label="Webhook signing key"
          value={signingKey}
          onFocus={(e) => e.currentTarget.select()}
          className="h-8 min-w-0 flex-1 rounded border border-border-strong bg-inset px-2 font-mono"
        />
        <button
          type="button"
          className="h-8 rounded border border-border-strong px-3 hover:bg-surface-head"
          onClick={() => {
            navigator.clipboard?.writeText(signingKey).then(
              () => setCopied(true),
              () => setCopied(false),
            );
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
        <button
          type="button"
          className="h-8 rounded bg-accent px-3 font-semibold text-white hover:brightness-110"
          onClick={onDone}
        >
          Done
        </button>
      </div>
    </section>
  );
}
