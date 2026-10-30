// Density (ADR-0038 edit 10, call 7): comfortable or compact rows, chosen per user in the
// user menu and remembered in this browser. With no choice, comfortable from 1440px wide.
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

export function defaultDensity(): Density {
  return (window.matchMedia?.("(min-width: 1440px)").matches ?? true) ? "comfortable" : "compact";
}

export function currentDensity(user: string): Density {
  return storedDensity(user) ?? defaultDensity();
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
