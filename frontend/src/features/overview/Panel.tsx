import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  meta?: ReactNode;
  children: ReactNode;
  wide?: boolean;
}

/** One Overview card: a titled section in the Dashboard card grammar (DESIGN 6.3). */
export function Panel({ title, meta, children, wide }: PanelProps) {
  return (
    <section
      aria-label={title}
      className={`flex min-w-0 flex-col gap-2 rounded-card border border-border bg-surface p-3 text-sm ${
        wide ? "col-span-full" : ""
      }`}
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-base font-semibold">{title}</h2>
        {meta ? <span className="ml-auto text-text-secondary">{meta}</span> : null}
      </div>
      {children}
    </section>
  );
}
