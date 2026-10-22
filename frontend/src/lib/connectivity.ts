import { useSyncExternalStore } from "react";

/**
 * Whether the server answered lately (F40). The API client reports each call: a call
 * that never reached the server (network error) or that a proxy answered for it (502,
 * 504, or a 503 that is not the server's own "busy") marks it unreachable; any answer
 * from the server clears that. Pages keep showing what they last loaded, and a banner
 * says how old it is.
 */
export interface Connectivity {
  /** When the server stopped answering; null while it answers. */
  downSince: Date | null;
  /** The last time any call got an answer from the server. */
  lastOkAt: Date | null;
}

let state: Connectivity = { downSince: null, lastOkAt: null };
const listeners = new Set<() => void>();

function emit(next: Connectivity) {
  state = next;
  listeners.forEach((l) => l());
}

export function reportReached(): void {
  const now = new Date();
  // Many calls succeed each minute: only tell listeners when something they show changes.
  if (state.downSince || !state.lastOkAt || now.getTime() - state.lastOkAt.getTime() > 30_000) {
    emit({ downSince: null, lastOkAt: now });
  } else {
    state = { ...state, lastOkAt: now };
  }
}

export function reportUnreachable(): void {
  if (!state.downSince) emit({ ...state, downSince: new Date() });
}

/** A proxy or load balancer answering because the server did not. */
export function unreachableStatus(status: number, code: string | undefined): boolean {
  return status === 502 || status === 504 || (status === 503 && code === undefined);
}

export function useConnectivity(): Connectivity {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => state,
  );
}

/** For tests. */
export function resetConnectivity(): void {
  emit({ downSince: null, lastOkAt: null });
}
