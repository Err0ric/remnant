import type { AlertKind } from "@/lib/api";

/** What fired, in words, for each kind of alert (ADR-0037 row 13). */
export const KIND_LABEL: Record<AlertKind, string> = {
  schedule: "Saved search flagged",
  rule: "Rule matched",
  gap: "Source stopped sending",
  ai_watch: "AI Watch",
};
