import { LogOut, Moon, Search, Sun } from "lucide-react";
import type { User } from "@/lib/api";
import { navigate } from "@/lib/route";
import { PRODUCT_NAME } from "@/lib/branding";
import type { Theme } from "@/lib/theme";

interface TopBarProps {
  theme: Theme;
  onToggleTheme: () => void;
  user?: User | null;
  onSignOut?: (() => void) | null;
  onOpenPalette?: () => void;
}

function isMac(): boolean {
  return /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
}

export function TopBar({ theme, onToggleTheme, user, onSignOut, onOpenPalette }: TopBarProps) {
  const next = theme === "dark" ? "light" : "dark";
  return (
    <header className="flex h-11 shrink-0 flex-wrap items-center gap-4 border-b border-black/20 bg-top px-4 text-white">
      <a
        href="/overview"
        aria-label={`${PRODUCT_NAME} overview`}
        className="flex items-center gap-2 font-semibold text-white no-underline"
        onClick={(e) => {
          e.preventDefault();
          navigate("overview");
        }}
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          aria-hidden="true"
          className="text-accent-text"
        >
          <path d="M4 18L10 6l4 8 2-4 4 8" />
        </svg>
        {PRODUCT_NAME}
      </a>
      <span className="text-white/40" aria-hidden="true">
        |
      </span>
      <span className="text-sm text-white/75">Security workspace</span>
      <button
        type="button"
        onClick={onOpenPalette}
        aria-label="Open the command palette"
        className="ml-6 flex h-7 w-full max-w-[420px] items-center gap-2 rounded border border-white/15 px-2.5 text-left text-sm text-white/60 hover:border-white/30 hover:text-white/80"
      >
        <Search size={14} aria-hidden />
        Go to a page, saved search, or source
        <kbd className="ml-auto rounded-badge border border-white/20 px-1 text-[11px] text-white/60">
          {isMac() ? "⌘K" : "Ctrl K"}
        </kbd>
      </button>
      <span className="ml-auto flex items-center gap-3 text-sm text-white/75">
        <span className="rounded-badge border border-white/20 px-2 text-xs font-normal">
          {window.location.host}
        </span>
        <button
          type="button"
          onClick={onToggleTheme}
          aria-label={`Switch to ${next} theme`}
          className="flex h-7 items-center gap-1.5 rounded border border-white/20 px-2.5 hover:bg-white/10"
        >
          {theme === "dark" ? <Sun size={14} aria-hidden /> : <Moon size={14} aria-hidden />}
          {theme === "dark" ? "Light" : "Dark"}
        </button>
        {user && onSignOut ? (
          <>
            <a
              href="/me"
              onClick={(e) => {
                e.preventDefault();
                navigate("me");
              }}
              className="flex items-center gap-1.5 rounded px-1.5 hover:bg-white/10"
              title="Your account and tokens"
            >
              <span className="font-semibold text-white">{user.username}</span>
              <span className="text-sm capitalize text-white/50">{user.role}</span>
            </a>
            <button
              type="button"
              onClick={onSignOut}
              className="flex h-7 items-center gap-1.5 rounded border border-white/20 px-2.5 hover:bg-white/10"
            >
              <LogOut size={14} aria-hidden />
              Sign out
            </button>
          </>
        ) : null}
      </span>
    </header>
  );
}
