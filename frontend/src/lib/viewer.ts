import { createContext, useContext } from "react";

/** What the signed-in viewer may open, for shared chrome (the header's tabs). Pages still
 * take their rights as props; the server enforces them either way. */
export const ViewerContext = createContext<{ isAdmin: boolean }>({ isAdmin: true });

export function useViewer() {
  return useContext(ViewerContext);
}
