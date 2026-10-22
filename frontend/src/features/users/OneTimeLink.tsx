import { useState } from "react";
import { PRODUCT_NAME } from "@/lib/branding";

interface OneTimeLinkProps {
  title: string;
  username: string;
  link: string;
  onDone: () => void;
}

const RELOGIN_NOTE =
  "If a sign-in page comes up first and you land on a page saying the link lost its code, open this link again now that you're signed in.";

/** The text to send with a link, so the forward-auth case is explained up front. */
export function linkMessage(username: string, link: string): string {
  return [
    `Use this link to set up how you sign in to ${PRODUCT_NAME} (account ${username}):`,
    link,
    "It works once and expires in 24 hours.",
    RELOGIN_NOTE,
  ].join("\n");
}

/** Shows an invite or reset link exactly once, with copy and a clear warning. */
export function OneTimeLink({ title, username, link, onDone }: OneTimeLinkProps) {
  const [copied, setCopied] = useState<"link" | "message" | null>(null);
  const copy = async (what: "link" | "message") => {
    try {
      await navigator.clipboard.writeText(what === "link" ? link : linkMessage(username, link));
      setCopied(what);
    } catch {
      setCopied(null); // the field stays selectable for manual copy
    }
  };
  return (
    <section aria-label={title} className="rounded-card border border-accent bg-accent-subtle p-4">
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="mt-1 text-sm text-text-secondary">
        Send this to <span className="font-semibold text-text">{username}</span> through a channel
        you trust. It works once, expires in 24 hours, and is not shown again.
      </p>
      <p className="mt-1 text-sm text-text-secondary">
        Behind a sign-in proxy (Authelia, oauth2-proxy), the code after{" "}
        <code className="font-mono">#</code> can be dropped on the way back from its login; they
        open the link again once signed in. Copy message includes that note.
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
          onClick={() => void copy("link")}
          className="h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head"
        >
          {copied === "link" ? "Copied" : "Copy"}
        </button>
        <button
          type="button"
          onClick={() => void copy("message")}
          className="h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head"
        >
          {copied === "message" ? "Copied" : "Copy message"}
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
