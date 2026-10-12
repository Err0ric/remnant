import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { SetupPage } from "./SetupPage";
import { SignInPage } from "./SignInPage";
import { api, setAuthLostHandler, setCsrfToken, type AuthState, type User } from "@/lib/api";

export const AUTH_KEY = ["auth-state"] as const;

interface AuthGateProps {
  children: (user: User | null, signOut: (() => void) | null) => ReactNode;
}

/**
 * The CSRF token is set as soon as the session state arrives, before any page renders.
 * Setting it in an effect was too late: React runs the pages' effects first, so the query
 * each page runs on open went out without it and was refused after every reload.
 */
async function loadAuthState(): Promise<AuthState> {
  const state = await api.authState();
  setCsrfToken(state.csrf_token ?? null);
  return state;
}

/** Shows setup or sign-in until the server says the caller may use the app. */
export function AuthGate({ children }: AuthGateProps) {
  const client = useQueryClient();
  const [signOutFailed, setSignOutFailed] = useState(false);
  const state = useQuery({ queryKey: AUTH_KEY, queryFn: loadAuthState, staleTime: Infinity });

  useEffect(() => {
    setAuthLostHandler(() => void client.invalidateQueries({ queryKey: AUTH_KEY }));
    return () => setAuthLostHandler(null);
  }, [client]);

  const data = state.data;

  const signedIn = (next: { user: User; csrf_token?: string }) => {
    setCsrfToken(next.csrf_token ?? null);
    client.setQueryData<AuthState>(AUTH_KEY, (prev) => ({
      mode: "login",
      user: next.user,
      csrf_token: next.csrf_token ?? null,
      sso: prev?.sso ?? null,
    }));
  };

  const signOut = async () => {
    try {
      await api.logout();
      setSignOutFailed(false);
    } catch {
      // The server may not have ended the session; say so rather than look signed out.
      setSignOutFailed(true);
    } finally {
      setCsrfToken(null);
      // Drop every cached result from the old session, then show sign-in.
      client.removeQueries({ predicate: (q) => q.queryKey[0] !== AUTH_KEY[0] });
      client.setQueryData<AuthState>(AUTH_KEY, (prev) => ({
        mode: "login",
        user: null,
        csrf_token: null,
        sso: prev?.sso ?? null,
      }));
    }
  };

  if (state.isPending) return <div className="min-h-full bg-bg" aria-busy="true" />;
  if (state.isError || !data) {
    return (
      <div className="flex min-h-full items-center justify-center bg-bg p-6 text-sm text-text-secondary">
        Cannot reach the server. Check that it is running and refresh.
      </div>
    );
  }
  if (data.mode === "setup") return <SetupPage onDone={signedIn} />;
  if (data.mode === "login" && !data.user) {
    return (
      <SignInPage
        sso={data.sso ?? null}
        onDone={(next) => {
          setSignOutFailed(false);
          signedIn(next);
        }}
        notice={
          signOutFailed
            ? "Sign-out did not reach the server, so that session may still be active until it expires. Sign in and sign out again, or ask an administrator to sign you out everywhere."
            : null
        }
      />
    );
  }
  return <>{children(data.user, data.mode === "login" ? () => void signOut() : null)}</>;
}
