import { createContext, useContext } from "react";

/** What the signed-in viewer may open, for shared chrome (the header's tabs). Pages still
 * take their rights as props; the server enforces them either way. `canRunSql` is false only
 * for an Auditor while Auditors may not run SQL (D220); `canAsk` follows it. `canViewPeople` is
 * View people in AI usage (D242); the server masks names without it, this only shapes copy.
 * `userId` keys what this browser keeps per user (the rail's Recent); "" in open mode. */
export const ViewerContext = createContext<{
  isAdmin: boolean;
  userId?: string;
  canAsk?: boolean;
  canRunSql?: boolean;
  canViewPeople?: boolean;
}>({
  isAdmin: true,
  canAsk: true,
  canRunSql: true,
  canViewPeople: true,
});

export function useViewer() {
  return useContext(ViewerContext);
}
