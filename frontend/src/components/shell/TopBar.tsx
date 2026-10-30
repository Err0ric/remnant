import { Menu, Moon, Search, Sun, X } from "lucide-react";
import { UserMenu } from "./UserMenu";
import type { User } from "@/lib/api";
import { AlertsButton, Freshness, InstallLabel } from "./Freshness";
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
    <header className="sticky top-0 z-30 grid h-12 shrink-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-b border-black/20 bg-top px-4 text-white md:gap-5 min-[1100px]:grid-cols-[216px_minmax(0,1fr)_auto]">
      <div className="flex min-w-0 items-center gap-3">
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
        {user !== undefined ? <InstallLabel /> : null}
      </div>
      {/* Centered, wide search (ADR-0038 edit 10). It opens the palette's list under it. */}
      <button
        id="top-search"
        type="button"
        onClick={onOpenPalette}
        aria-label="Search pages, addresses, users, hosts, AI services"
        aria-keyshortcuts="Control+K Meta+K"
        className="mx-auto flex h-9 w-full max-w-[680px] min-w-0 items-center gap-2.5 rounded border border-white/15 bg-white/5 px-3 text-base text-white/60 hover:border-white/30 hover:bg-white/10 hover:text-white/80"
      >
        <Search size={16} aria-hidden className="shrink-0" />
        <span className="hidden truncate sm:inline">
          Search pages, addresses, users, hosts, AI services
        </span>
        <kbd className="ml-auto hidden shrink-0 rounded-badge border border-white/20 px-1 text-[11px] text-white/60 md:inline">
          {isMac() ? "⌘K" : "Ctrl K"}
        </kbd>
      </button>
      <span className="flex shrink-0 items-center justify-end gap-2 text-base text-white/75 sm:gap-3">
        {ENVIRONMENT_LABEL ? (
          <span
            className="hidden rounded-badge border border-white/20 px-2 text-xs font-normal sm:inline"
            title="Set by the administrator (server.environment_label)"
          >
            {ENVIRONMENT_LABEL}
          </span>
        ) : null}
        {user !== undefined ? (
          <>
            <Freshness />
            <AlertsButton />
          </>
        ) : null}
        <button
          type="button"
          onClick={onToggleTheme}
          aria-label={`Switch to ${next} theme`}
          title={`Switch to ${next} theme`}
          className="flex h-8 w-8 items-center justify-center rounded border border-white/20 hover:bg-white/10"
        >
          {theme === "dark" ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
        </button>
        {user && onSignOut ? <UserMenu user={user} onSignOut={onSignOut} /> : null}
      </span>
    </header>
  );
}
