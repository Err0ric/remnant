import { Sparkles } from "lucide-react";

interface AiToggleProps {
  on: boolean;
  onChange: (on: boolean) => void;
}

/**
 * The sparkle switch at the start of the search bar (ADR-0016 row 1). On, the text is a
 * plain-English question for Ask; the SQL it writes is shown and runs only on click.
 */
export function AiToggle({ on, onChange }: AiToggleProps) {
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label="Ask in plain English"
      title={on ? "Plain English: a model writes the SQL, you run it" : "Switch to plain English"}
      onClick={() => onChange(!on)}
      className={`flex h-9 shrink-0 items-center gap-1.5 rounded border px-2.5 text-sm font-semibold ${
        on
          ? "border-accent bg-accent-subtle text-accent-text"
          : "border-border-strong text-text-secondary hover:bg-surface-head hover:text-text"
      }`}
    >
      <Sparkles size={15} aria-hidden />
      <span aria-hidden="true">AI</span>
    </button>
  );
}
