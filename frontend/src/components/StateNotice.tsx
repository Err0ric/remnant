import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface StateNoticeProps {
  children: ReactNode;
  /** A blind state (a source down, detection not running): adds the warn tint. */
  blind?: boolean;
  className?: string;
}

/** A state notice (DESIGN.md 6.0 and 7): one line that says what the viewer is not seeing
 * or what is not running. Not help text and never removed. A 1px border with a 2px warn bar
 * on the left; blind notices add the warn tint. */
export function StateNotice({ children, blind = false, className }: StateNoticeProps) {
  return (
    <p
      role="note"
      data-state-notice={blind ? "blind" : ""}
      className={cn(
        "rounded border border-border border-l-2 border-l-warn px-3 py-1.5 text-sm",
        blind ? "bg-warn-tint text-text" : "text-text-secondary",
        className,
      )}
    >
      {children}
    </p>
  );
}
