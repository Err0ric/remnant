import type { MouseEvent } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { Truncate } from "@/components/Truncate";
import { navigate, pathFor, usePathname } from "@/lib/route";

/** An address no page claims (DESIGN.md 6.0, not found): the shell stays, the address stays
 * as typed so the person can see and fix it, and one link goes home. The path is untrusted
 * input: a text node, cut in the middle when long. Home is the Dashboard for every role. */
export function NotFoundPage() {
  const path = usePathname();
  const home = (e: MouseEvent) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    navigate("dashboard");
  };
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader title="Page not found" />
      {/* The page body's padding and content column (as Ask AI): the line starts under the
       * title, and a long address is cut inside the column, not at the window's edge. */}
      <div
        data-empty="not-found"
        className="flex max-w-[1240px] flex-col items-start gap-1 px-5 py-3 text-sm"
      >
        <p className="flex min-w-0 max-w-full items-baseline gap-1 text-text">
          <span className="shrink-0">There is no page at</span>
          <Truncate value={path} kind="name" className="font-mono" />
        </p>
        <a href={pathFor("dashboard")} onClick={home} className="text-accent-text hover:underline">
          Go to the Dashboard
        </a>
      </div>
    </div>
  );
}
