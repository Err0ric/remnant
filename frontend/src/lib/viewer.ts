import { createContext, useContext } from "react";

/** What the signed-in viewer may open, for shared chrome (the header's tabs). Pages still
 * take their rights as props; the server enforces them either way. `canRunSql` is false only
 * for an Auditor while Auditors may not run SQL (D220); `canAsk` follows it. */
export const ViewerContext = createContext<{
  isAdmin: boolean;
  canAsk?: boolean;
  canRunSql?: boolean;
}>({
  isAdmin: true,
  canAsk: true,
  canRunSql: true,
});

export function useViewer() {
  return useContext(ViewerContext);
}
