import { useSyncExternalStore } from "react";

/** The AI provider Ask uses, chosen in Ask or the command palette. Remembered per browser. */
const KEY = "ask-provider";
const listeners = new Set<() => void>();
let current: string = read();

function read(): string {
  try {
    return window.localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function setAskProvider(id: string): void {
  current = id;
  try {
    window.localStorage.setItem(KEY, id);
  } catch {
    // Storage blocked: the choice still holds for this page load.
  }
  listeners.forEach((l) => l());
}

function subscribe(callback: () => void) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

export function useAskProvider(): string {
  return useSyncExternalStore(subscribe, () => current);
}
