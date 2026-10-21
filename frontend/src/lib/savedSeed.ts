/** A one-shot "open this saved search" handoff (command palette), taken once by the page. */
let pending: string | null = null;
let version = 0;
const listeners = new Set<() => void>();

export function openSavedSearch(id: string): void {
  pending = id;
  version += 1; // remounts an open Saved searches page so it takes the handoff
  listeners.forEach((l) => l());
}

export function takeSavedSeed(): string | null {
  const value = pending;
  pending = null;
  return value;
}

export function subscribeSaved(callback: () => void): () => void {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

export function savedVersion(): number {
  return version;
}
