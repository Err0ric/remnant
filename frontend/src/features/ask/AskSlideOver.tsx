import { X } from "lucide-react";
import { useEffect } from "react";
import { closeAsk, useAskSlideOver } from "@/lib/askSlideOver";
import { navigate } from "@/lib/route";
import { rangeStart } from "@/lib/search";
import { seedSearch } from "@/lib/searchSeed";
import { AskThread } from "./AskThread";

/** Ask AI from anywhere (ADR-0042 row 16; Ctrl+K "Ask AI"): a panel on the right over the
 * current page, the last 24 hours on every source the viewer may read. Escape closes it.
 * For asking, not for reading events (those expand inline, DESIGN.md 8). */
export function AskSlideOver({ isAdmin }: { isAdmin: boolean }) {
  const { open, question } = useAskSlideOver();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeAsk();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  if (!open) return null;
  return (
    <aside
      role="dialog"
      aria-label="Ask AI"
      className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[560px] flex-col border-l border-border bg-bg shadow-lg"
    >
      <div className="flex items-center gap-3 border-b border-border bg-surface-head px-4 py-2.5">
        <h2 className="text-base font-semibold">Ask AI</h2>
        <span className="text-sm text-text-muted">Last 24 hours, your sources</span>
        <button
          type="button"
          onClick={closeAsk}
          aria-label="Close Ask AI"
          className="ml-auto rounded p-1 text-text-secondary hover:bg-surface"
        >
          <X size={16} strokeWidth={1.5} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <AskThread
          // A new question from the palette starts a new thread.
          key={question}
          start={rangeStart("24h")}
          sources={[]}
          isAdmin={isAdmin}
          initialQuestion={question}
          autoFocus
          onEdit={(sql, asked) => {
            seedSearch({
              sql,
              range: "24h",
              origin: asked ? `From Ask AI: ${asked}` : "From Ask AI",
              askQuestion: asked,
            });
            closeAsk();
            navigate("logs");
          }}
        />
      </div>
    </aside>
  );
}
