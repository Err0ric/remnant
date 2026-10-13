import { LogOut, Menu, Moon, Search, Sun, X } from "lucide-react";
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
  menuOpen?: boolean;
  onToggleMenu?: () => void;
}

function isMac(): boolean {
  return /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
}

export function TopBar({
  theme,
  onToggleTheme,
  user,
  onSignOut,
  onOpenPalette,
  menuOpen = false,
  onToggleMenu,
}: TopBarProps) {
  const next = theme === "dark" ? "light" : "dark";
  return (
    <header className="flex h-11 shrink-0 items-center gap-3 border-b border-black/20 bg-top px-4 text-white md:gap-4">
      {onToggleMenu ? (
        <button
          type="button"
          onClick={onToggleMenu}
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
          aria-controls="primary-nav"
          className="-ml-1 flex h-7 w-7 items-center justify-center rounded hover:bg-white/10 md:hidden"
        >
          {menuOpen ? <X size={16} aria-hidden /> : <Menu size={16} aria-hidden />}
        </button>
      ) : null}
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
      <span className="hidden text-white/40 lg:inline" aria-hidden="true">
        |
      </span>
      <span className="hidden text-sm text-white/75 lg:inline">Security workspace</span>
      <button
        type="button"
        onClick={onOpenPalette}
        aria-label="Open the command palette"
        className="flex h-7 w-7 shrink-0 items-center justify-center gap-2 rounded border border-white/15 text-left text-sm text-white/60 hover:border-white/30 hover:text-white/80 sm:w-full sm:max-w-[420px] sm:shrink sm:justify-start sm:px-2.5 lg:ml-6"
      >
        <Search size={14} aria-hidden />
        <span className="hidden truncate sm:inline">Go to a page, saved search, or source</span>
        <kbd className="ml-auto hidden rounded-badge border border-white/20 px-1 text-[11px] text-white/60 md:inline">
          {isMac() ? "⌘K" : "Ctrl K"}
        </kbd>
      </button>
      <span className="ml-auto flex shrink-0 items-center gap-2 text-sm text-white/75 sm:gap-3">
        <span className="hidden rounded-badge border border-white/20 px-2 text-xs font-normal xl:inline">
          {window.location.host}
        </span>
        <button
          type="button"
          onClick={onToggleTheme}
          aria-label={`Switch to ${next} theme`}
          className="flex h-7 items-center gap-1.5 rounded border border-white/20 px-2.5 hover:bg-white/10"
        >
          {theme === "dark" ? <Sun size={14} aria-hidden /> : <Moon size={14} aria-hidden />}
          <span className="hidden sm:inline">{theme === "dark" ? "Light" : "Dark"}</span>
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
              <span className="hidden text-sm capitalize text-white/50 sm:inline">{user.role}</span>
            </a>
            <button
              type="button"
              onClick={onSignOut}
              className="flex h-7 items-center gap-1.5 rounded border border-white/20 px-2.5 hover:bg-white/10"
            >
              <LogOut size={14} aria-hidden />
              <span className="sr-only sm:not-sr-only">Sign out</span>
            </button>
          </>
        ) : null}
      </span>
    </header>
  );
}
