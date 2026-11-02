import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface SectionTitleProps {
  children: ReactNode;
  /** Heading level; a section is an h2 on its page. */
  as?: "h2" | "h3";
  className?: string;
  id?: string;
}

/** The title of a page section (DESIGN.md 7): a soft slate pill, brighter and bolder than
 * the data, with no link color and no hover state, so it reads as a title, not a control. */
export function SectionTitle({ children, as: Tag = "h2", className, id }: SectionTitleProps) {
  return (
    <Tag
      id={id}
      data-title="section"
      className={cn(
        "inline-flex w-fit max-w-full items-center rounded-badge bg-section-bg px-2 py-0.5 text-md font-bold text-section-text",
        className,
      )}
    >
      {children}
    </Tag>
  );
}
