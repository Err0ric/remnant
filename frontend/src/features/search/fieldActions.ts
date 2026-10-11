import { createContext } from "react";

/** Filter for, Filter out, and Top values on a field in an expanded event (ADR-0009). */
export interface FieldActions {
  /** Columns that take these actions (text and number columns, not times or JSON). */
  fields: ReadonlySet<string>;
  filter: (field: string, value: string, exclude: boolean) => void;
  top: (field: string) => void;
}

export const FieldActionsContext = createContext<FieldActions | null>(null);
