import { useId, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  help?: string;
}

/** Label above, input, help text below (DESIGN.md settings forms). */
export function Field({ label, help, className, ...input }: FieldProps) {
  const id = useId();
  const helpId = help ? `${id}-help` : undefined;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-semibold text-text">
        {label}
      </label>
      <input
        id={id}
        aria-describedby={helpId}
        {...input}
        className={cn(
          "h-9 rounded border border-border-strong bg-inset px-2.5 text-sm text-text outline-none focus:border-accent focus:ring-1 focus:ring-focus-ring",
          className,
        )}
      />
      {help ? (
        <p id={helpId} className="text-sm text-text-muted">
          {help}
        </p>
      ) : null}
    </div>
  );
}
