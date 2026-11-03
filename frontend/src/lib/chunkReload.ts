/** A page chunk that no longer exists after an update (an old index.html in an open tab)
 * reloads the page once, so the new build loads (owner 2026-11-02). A guard in session
 * storage stops a loop: a second failure within GUARD_MS shows the error page instead. */

export const RELOAD_KEY = "chunk-reload-at";
export const GUARD_MS = 60_000;

export function isChunkError(err: unknown): boolean {
  const text = err instanceof Error ? `${err.name} ${err.message}` : String(err);
  return /ChunkLoadError|Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Unable to preload CSS|Loading chunk [\w-]+ failed/i.test(
    text,
  );
}

interface Store {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function session(): Store | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** Reload once; false when a reload already happened within the guard (or storage is
 * unavailable, so a loop cannot be ruled out). */
export function reloadOnce(
  store: Store | null = session(),
  reload: () => void = () => window.location.reload(),
  now: number = Date.now(),
): boolean {
  if (!store) return false;
  try {
    const last = Number(store.getItem(RELOAD_KEY) ?? "0");
    if (now - last < GUARD_MS) return false;
    store.setItem(RELOAD_KEY, String(now));
  } catch {
    return false;
  }
  reload();
  return true;
}

/** For React.lazy: a chunk error reloads once and waits; anything else is thrown. */
export function withChunkReload<T>(load: () => Promise<T>): () => Promise<T> {
  return () =>
    load().catch((err: unknown) => {
      if (isChunkError(err) && reloadOnce()) return new Promise<T>(() => undefined);
      throw err;
    });
}
