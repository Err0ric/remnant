import type { ReactNode } from "react";
import type { User } from "@/lib/api";
import { useCanRunSql } from "@/lib/sqlAccess";
import { ViewerContext, useViewer } from "@/lib/viewer";

interface ViewerProviderProps {
  user: User | null;
  children: ReactNode;
}

/** The viewer's rights for shared chrome. Open mode (no accounts) is the local admin. */
export function ViewerProvider({ user, children }: ViewerProviderProps) {
  const canRunSql = useCanRunSql(user);
  return (
    <ViewerContext.Provider
      value={{ isAdmin: !user || user.role === "admin", canAsk: canRunSql, canRunSql }}
    >
      {children}
    </ViewerContext.Provider>
  );
}

interface SqlOnlyProps {
  fallback: ReactNode;
  children: ReactNode;
}

/** Children for viewers who may run SQL; `fallback` for an Auditor while it is off (D220). */
export function SqlOnly({ fallback, children }: SqlOnlyProps) {
  const { canRunSql = true } = useViewer();
  return <>{canRunSql ? children : fallback}</>;
}
