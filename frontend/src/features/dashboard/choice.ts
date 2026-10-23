/** The dashboard this viewer last opened (ADR-0034), kept in this browser only. New
 * panels from Search go there. */
const KEY = "dashboard-current";

export function currentDashboard(): string | null {
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null; // storage blocked: the first dashboard is used
  }
}

export function rememberDashboard(id: string): void {
  try {
    window.localStorage.setItem(KEY, id);
  } catch {
    // storage blocked: nothing to remember
  }
}
