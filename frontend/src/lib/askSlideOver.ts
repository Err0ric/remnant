import { useSyncExternalStore } from "react";

/** Whether the Ask slide-over is open, and the question it opens with (ADR-0042 row 16). */
interface State {
  open: boolean;
  question: string;
}

const listeners = new Set<() => void>();
let state: State = { open: false, question: "" };

function set(next: State) {
  state = next;
  listeners.forEach((l) => l());
}

export function openAsk(question = ""): void {
  set({ open: true, question });
}

export function closeAsk(): void {
  set({ open: false, question: "" });
}

function subscribe(callback: () => void) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

export function useAskSlideOver(): State {
  return useSyncExternalStore(subscribe, () => state);
}
