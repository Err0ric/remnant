import type { MouseEvent } from "react";
import { closeAsk } from "@/lib/askSlideOver";
import { entityHref, openEntity } from "@/lib/entity";
import type { AskDirect } from "@/lib/api";

/** Opens the page here (the slide-over closes); a modified click keeps the browser's own. */
function open(e: MouseEvent<HTMLAnchorElement>, d: AskDirect): void {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  closeAsk();
  openEntity({ kind: d.kind, value: d.value }, undefined, d.range);
}

/** A question that is only an address (D276): its page, with the page's sections in
 * brief. Written by code from the server's answer; no model was called. */
export function AskDirectAnswer({ found }: { found: AskDirect[] }) {
  return (
    <div role="status" className="flex flex-col gap-2 text-sm">
      {found.map((d) => (
        <div key={`${d.kind}:${d.value}`} className="flex flex-col gap-1.5">
          {/* Said once, first: the window the server read, the page's, not Ask's. */}
          <p className="text-text-muted">
            Looked up directly for {d.window}, the address page's window, not the time chosen above.
            No AI model was used.
          </p>
          <p>
            <span className="font-mono">{d.value}</span> is an address.{" "}
            <a
              href={entityHref({ kind: d.kind, value: d.value }, undefined, d.range)}
              onClick={(e) => open(e, d)}
              className="font-semibold text-accent-text hover:underline"
            >
              Open the address page
            </a>
          </p>
          {d.sections.length ? (
            <ul aria-label={`On the page for ${d.value}`} className="flex flex-col gap-0.5">
              {d.sections.map((s) => (
                <li key={s.section} className="flex gap-2">
                  <span className="text-text-secondary">{s.title}:</span>
                  <span>
                    {s.state === "ok"
                      ? s.count_words
                      : s.state === "no_source"
                        ? "no source you may read"
                        : "could not be read"}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ))}
    </div>
  );
}
