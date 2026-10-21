import type { ReactNode } from "react";

interface PageHeaderProps {
  crumbs: string[];
  title: string;
  commands?: ReactNode;
  meta?: ReactNode;
}

export function PageHeader({ crumbs, title, commands, meta }: PageHeaderProps) {
  return (
    <div className="px-5 pt-3">
      <div className="text-sm text-text-secondary">{crumbs.join("  ›  ")}</div>
      <h1 className="mb-2 mt-1 text-lg">{title}</h1>
      <div className="flex flex-wrap items-center gap-1 border-b border-border py-1">
        {commands}
        {meta ? <span className="ml-auto text-sm text-text-secondary">{meta}</span> : null}
      </div>
    </div>
  );
}

interface CommandProps {
  label: string;
  onClick?: () => void;
  primary?: boolean;
  disabled?: boolean;
  title?: string;
}

export function Command({ label, onClick, primary, disabled, title }: CommandProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`h-8 rounded px-3 hover:bg-surface-head disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent ${
        primary ? "font-semibold text-accent-text" : "text-text"
      }`}
    >
      {label}
    </button>
  );
}
