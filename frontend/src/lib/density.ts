// Density (ADR-0052 section 3.10, D248): Comfortable is the default for every role and every
// screen width. Compact is a per-user choice in the user menu, remembered in this browser.
export type Density = "comfortable" | "compact";

const PREFIX = "app.density.";

function key(user: string): string {
  return `${PREFIX}${user || "local"}`;
}

export function storedDensity(user: string): Density | null {
  try {
    const v = window.localStorage.getItem(key(user));
    return v === "comfortable" || v === "compact" ? v : null;
  } catch {
    return null;
  }
}

export const DEFAULT_DENSITY: Density = "comfortable";

export function currentDensity(user: string): Density {
  return storedDensity(user) ?? DEFAULT_DENSITY;
}

/** Applies a density to the page; `save` also remembers it for this user. */
export function applyDensity(user: string, density: Density, save = false): void {
  document.documentElement.dataset.density = density;
  if (!save) return;
  try {
    window.localStorage.setItem(key(user), density);
  } catch {
    // Storage can be unavailable; the density still applies for this session.
  }
}
