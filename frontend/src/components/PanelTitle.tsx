import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface PanelTitleProps {
  children: ReactNode;
  /** h3 inside a section; span for a KPI label or a chart caption. */
  as?: "h2" | "h3" | "h4" | "span" | "figcaption";
  className?: string;
  title?: string;
  id?: string;
}

/** A title inside a section: a panel, card, chart, or KPI label (DESIGN.md 7). Small upper
 * case with wider letter spacing in a brighter color than the data; clearly below a
 * section title, with no link color and no hover state. */
export function PanelTitle({ children, as: Tag = "h3", className, title, id }: PanelTitleProps) {
  return (
    <Tag
      id={id}
      title={title}
      data-title="panel"
      className={cn("text-xs font-semibold uppercase tracking-wider text-panel-title", className)}
    >
      {children}
    </Tag>
  );
}
