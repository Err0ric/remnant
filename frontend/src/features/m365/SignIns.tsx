import { useState } from "react";
import type { M365Overview, SignInClassFilter, SignInMode } from "@/lib/api";
import { cn } from "@/lib/cn";
import { EventList } from "./EventList";
import { useSignInAbout } from "./signInCounting";

const CLASSES: { id: SignInClassFilter; label: string }[] = [
  { id: "failed", label: "Real failures" },
  { id: "interrupted", label: "Interrupted" },
  { id: "expired", label: "Expired" },
  { id: "other", label: "Other" },
  { id: "all", label: "All" },
];
const MODES: { id: SignInMode; label: string }[] = [
  { id: "all", label: "Everyone" },
  { id: "interactive", label: "Interactive" },
  { id: "noninteractive", label: "Non-interactive" },
];

function Choice<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { id: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex rounded border border-border">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          aria-pressed={o.id === value}
          onClick={() => onChange(o.id)}
          className={cn(
            "h-7 px-2.5 text-sm first:rounded-l last:rounded-r",
            o.id === value
              ? "bg-surface-head font-semibold text-text"
              : "text-text-secondary hover:text-text",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Microsoft 365 > Sign-ins (D158): real failures first, every class one click away, and
 * sign-ins the person made apart from those an app made in the background. */
export function SignIns({ m }: { m: M365Overview }) {
  const [cls, setCls] = useState<SignInClassFilter>("failed");
  const [mode, setMode] = useState<SignInMode>("all");
  const about = useSignInAbout();
  const sql = m.sign_in_lists?.[cls]?.[mode] ?? m.lists.sign_ins;
  const title =
    cls === "all" ? "Sign-ins" : `Sign-ins: ${CLASSES.find((c) => c.id === cls)?.label}`;
  return (
    <EventList
      title={title}
      sql={sql}
      m={m}
      controls={
        <>
          <Choice label="Outcome" options={CLASSES} value={cls} onChange={setCls} />
          <Choice label="Who signed in" options={MODES} value={mode} onChange={setMode} />
          <span
            role="img"
            aria-label={`How this is counted: ${about}`}
            title={`How this is counted: ${about}`}
            className="flex size-3.5 shrink-0 cursor-help items-center justify-center rounded-full border border-text-muted text-[10px] font-semibold leading-none text-text-muted"
          >
            i
          </span>
        </>
      }
    />
  );
}
