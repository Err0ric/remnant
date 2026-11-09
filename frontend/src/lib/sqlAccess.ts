import { useQuery } from "@tanstack/react-query";
import { api, type User } from "@/lib/api";

/** Plain explanation shown where an Auditor's SQL entry points would be (D220). */
export const AUDITOR_SQL_OFF =
  "Auditors cannot run SQL on this install. You can still review the audit log, dashboards, and reports. An administrator can allow Auditors to run SQL in Settings > Users and access.";

/** May this viewer run SQL (Logs, Ask, saved-search runs, export)? Everyone but an Auditor;
 * an Auditor only while an admin has turned the setting on. The server enforces it either way. */
export function useCanRunSql(user: User | null): boolean {
  const auditor = user?.role === "auditor";
  const setting = useQuery({
    queryKey: ["auditor-sql"],
    queryFn: api.auditorSql,
    enabled: auditor,
  });
  return !auditor || setting.data?.enabled === true;
}
