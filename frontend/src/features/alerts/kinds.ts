import type { AlertKind } from "@/lib/api";

/** What fired, in words, for each kind of alert (ADR-0037 row 13). */
export const KIND_LABEL: Record<AlertKind, string> = {
  schedule: "Saved search flagged",
  rule: "Rule matched",
  gap: "Source stopped sending",
  ai_watch: "AI Watch",
};

/** Where an AI Watch alert's people would show, without View people in AI usage (D242). */
export const NAMES_HIDDEN =
  "Names are hidden. An admin can turn on View people in AI usage for you.";

/** Alerts in sources the viewer cannot read: said once, never counted (owner, 2026-11-12). */
export const RESTRICTED_NOTE =
  "Some alerts are in sources you can't read. Ask an admin for access.";
