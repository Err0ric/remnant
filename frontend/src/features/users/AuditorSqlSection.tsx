import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SectionTitle } from "@/components/SectionTitle";
import { ApiError, api } from "@/lib/api";

/** Settings > Users and access: the one setting that lets Auditors run SQL (D220). Admins
 * only (the page is admin only, and the server refuses anyone else); every change is audited. */
export function AuditorSqlSection() {
  const client = useQueryClient();
  const setting = useQuery({ queryKey: ["auditor-sql"], queryFn: api.auditorSql });
  const save = useMutation({
    mutationFn: api.setAuditorSql,
    onSuccess: (data) => client.setQueryData(["auditor-sql"], data),
  });
  const on = setting.data?.enabled ?? false;

  return (
    <section
      aria-label="Auditor access"
      className="flex flex-col gap-2 rounded-card border border-border bg-surface p-4 text-sm"
    >
      <SectionTitle>Auditor access</SectionTitle>
      <label className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={on}
          disabled={setting.data === undefined || save.isPending}
          onChange={(e) => save.mutate(e.target.checked)}
          className="mt-0.5"
        />
        <span>
          <span className="font-semibold">Let Auditors run SQL</span>
          <span className="block text-text-secondary">
            Off by default. When off, Auditors review the audit log, dashboards, and reports, but
            cannot use Logs, Ask, saved-search runs, export, the command line, or the MCP server.
            When on, they search only the sources their groups grant. Each change is recorded in the
            audit log.
          </span>
        </span>
      </label>
      {setting.isError || save.isError ? (
        <p role="alert" className="text-danger">
          {(save.error ?? setting.error) instanceof ApiError
            ? (save.error ?? setting.error)?.message
            : "Could not save"}
        </p>
      ) : null}
    </section>
  );
}
