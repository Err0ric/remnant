/** Client-side errors reported to the server (owner 2026-11-02), so a blank or broken page
 * shows on Health and in the server's journal. Only the error's kind, a short message with
 * quoted text and long values removed, the page path, and the build: never log content. */

const MAX_PER_LOAD = 5;
let sent = 0;
let csrf: () => string | null = () => null;

/** api.ts hands over its CSRF token getter (it owns the token). */
export function setErrorCsrf(get: () => string | null): void {
  csrf = get;
}

/** The running build: the hashed name of the entry script ("index-BdM5148w"). */
export function buildId(): string {
  const s = document.querySelector<HTMLScriptElement>('script[type="module"][src*="assets/"]');
  const m = s ? /assets\/([\w.-]+)\.js/.exec(s.src) : null;
  return m?.[1] ?? "dev";
}

/** A short error id the person can quote ("e-3f9a1c"). */
export function errorId(): string {
  const n = Math.floor(Math.random() * 0xffffff);
  return `e-${n.toString(16).padStart(6, "0")}`;
}

/** Strip anything that could be record content: quoted text, long tokens, addresses. */
export function scrub(message: string): string {
  return message
    .replace(/"[^"]*"|'[^']*'|`[^`]*`/g, "…")
    .replace(/\b[\w.+-]+@[\w.-]+\b/g, "…")
    .replace(/\b\d{1,3}(?:\.\d{1,3}){3}\b/g, "…")
    .replace(/\S{41,}/g, "…")
    .slice(0, 200);
}

export type ErrorKind = "render" | "panel" | "chunk" | "unhandled";

export function reportClientError(kind: ErrorKind, error: unknown, id: string): void {
  if (sent >= MAX_PER_LOAD) return;
  sent += 1;
  const name = error instanceof Error ? error.name : "Error";
  const message = scrub(error instanceof Error ? error.message : String(error));
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = csrf();
  if (token) headers["X-CSRF-Token"] = token;
  void fetch("/api/client-errors", {
    method: "POST",
    credentials: "same-origin",
    headers,
    body: JSON.stringify({
      kind,
      error_id: id,
      name: name.slice(0, 40),
      message,
      route: window.location.pathname.slice(0, 120),
      build: buildId(),
    }),
  }).catch(() => undefined); // reporting never breaks the page
}

/** Test hook: start counting again. */
export function resetReports(): void {
  sent = 0;
}
