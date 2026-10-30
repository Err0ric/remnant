import { useEffect, useRef, useState } from "react";
import { ChevronDown, LogOut } from "lucide-react";
import type { User } from "@/lib/api";
import { applyDensity, currentDensity, type Density } from "@/lib/density";
import { navigate } from "@/lib/route";
import { cn } from "@/lib/cn";

interface UserMenuProps {
  user: User;
  onSignOut: () => void;
}

const DENSITIES: { id: Density; label: string; hint: string }[] = [
  { id: "comfortable", label: "Comfortable", hint: "Taller rows" },
  { id: "compact", label: "Compact", hint: "More rows on screen" },
];

/** Account, row density (ADR-0038 edit 10, call 7), and sign out. */
export function UserMenu({ user, onSignOut }: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const [density, setDensity] = useState<Density>(() => currentDensity(user.username));
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    applyDensity(user.username, density);
  }, [user.username, density]);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const choose = (d: Density) => {
    applyDensity(user.username, d, true);
    setDensity(d);
  };

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex h-8 items-center gap-1.5 rounded px-1.5 hover:bg-white/10"
      >
        <span className="font-semibold text-white">{user.username}</span>
        <span className="hidden text-sm capitalize text-white/50 sm:inline">{user.role}</span>
        <ChevronDown size={14} aria-hidden className="text-white/50" />
      </button>
      {open ? (
        <div className="absolute right-0 top-full z-50 mt-1 w-60 rounded-card border border-border bg-surface p-1.5 text-text shadow-lg">
          <a
            href="/me"
            onClick={(e) => {
              e.preventDefault();
              setOpen(false);
              navigate("me");
            }}
            className="block rounded px-2.5 py-1.5 text-text no-underline hover:bg-surface-head"
          >
            Your account and tokens
          </a>
          <div role="group" aria-label="Density" className="mt-1 border-t border-border pt-1.5">
            <div className="px-2.5 pb-1 text-sm text-text-muted">Density</div>
            {DENSITIES.map((d) => (
              <button
                key={d.id}
                type="button"
                aria-pressed={density === d.id}
                onClick={() => choose(d.id)}
                className={cn(
                  "flex w-full items-baseline justify-between rounded px-2.5 py-1.5 text-left hover:bg-surface-head",
                  density === d.id && "bg-accent-subtle text-accent-text",
                )}
              >
                <span className="font-semibold">{d.label}</span>
                <span className="text-sm text-text-muted">{d.hint}</span>
              </button>
            ))}
          </div>
          <div className="mt-1 border-t border-border pt-1.5">
            <button
              type="button"
              onClick={onSignOut}
              className="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left hover:bg-surface-head"
            >
              <LogOut size={16} aria-hidden />
              Sign out
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
