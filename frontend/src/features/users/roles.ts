import type { Role } from "@/lib/api";

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Admin",
  analyst: "Analyst",
  auditor: "Auditor",
};

// SPEC 3.6 role definitions, in plain words.
export const ROLE_HELP: Record<Role, string> = {
  admin: "Manages users, groups, sources, and settings. Sees every source.",
  analyst: "Searches and investigates the sources their groups grant.",
  auditor: "Read-only: searches granted sources and reviews the audit log. No edits.",
};
