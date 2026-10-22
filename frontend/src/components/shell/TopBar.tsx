import { LogOut, Menu, Moon, Search, Sun, X } from "lucide-react";
import type { User } from "@/lib/api";
import { navigate } from "@/lib/route";
import { ENVIRONMENT_LABEL, PRODUCT_NAME } from "@/lib/branding";
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
    <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center gap-3 border-b border-black/20 bg-top px-4 text-white md:gap-5">
      {onToggleMenu ? (
        <button
          type="button"
          onClick={onToggleMenu}
          aria-label={menuOpen ? "Close menu" : "Open menu"}
          aria-expanded={menuOpen}
          aria-controls="primary-nav"
          className="-ml-1 flex h-8 w-8 items-center justify-center rounded hover:bg-white/10 md:hidden"
        >
          {menuOpen ? <X size={18} aria-hidden /> : <Menu size={18} aria-hidden />}
        </button>
      ) : null}
      <a
        href="/"
        aria-label={`${PRODUCT_NAME} home`}
        className="flex items-center gap-2 text-md text-white no-underline"
        onClick={(e) => {
          e.preventDefault();
          navigate("home");
        }}
      >
        <svg
          width="22"
          height="22"
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
      <span className="hidden text-base text-white/75 lg:inline">Security workspace</span>
      <button
        type="button"
        onClick={onOpenPalette}
        aria-label="Open the command palette"
        title="Jump to a page, saved search, source, or action"
        className="flex h-8 shrink-0 items-center gap-2 rounded border border-white/15 bg-white/5 px-2.5 text-base text-white/75 hover:border-white/30 hover:bg-white/10 hover:text-white lg:ml-4"
      >
        <Search size={16} aria-hidden />
        <span className="hidden sm:inline">Jump to</span>
        <kbd className="hidden rounded-badge border border-white/20 px-1 text-[11px] text-white/60 md:inline">
          {isMac() ? "⌘K" : "Ctrl K"}
        </kbd>
      </button>
      <span className="ml-auto flex shrink-0 items-center gap-2 text-base text-white/75 sm:gap-3">
        {ENVIRONMENT_LABEL ? (
          <span
            className="hidden rounded-badge border border-white/20 px-2 text-xs font-normal sm:inline"
            title="Set by the administrator (server.environment_label)"
          >
            {ENVIRONMENT_LABEL}
          </span>
        ) : null}
        <button
          type="button"
          onClick={onToggleTheme}
          aria-label={`Switch to ${next} theme`}
          className="flex h-8 items-center gap-1.5 rounded border border-white/20 px-2.5 hover:bg-white/10"
        >
          {theme === "dark" ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
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
              className="flex h-8 items-center gap-1.5 rounded border border-white/20 px-2.5 hover:bg-white/10"
            >
              <LogOut size={16} aria-hidden />
              <span className="sr-only sm:not-sr-only">Sign out</span>
            </button>
          </>
        ) : null}
      </span>
    </header>
  );
}
