import { PageHeader } from "@/components/shell/PageHeader";
import { AUDITOR_SQL_OFF } from "@/lib/sqlAccess";
import { navigate } from "@/lib/route";

/** Logs for an Auditor while Auditors may not run SQL (D220): no editor, a plain reason. */
export function SqlOffNotice() {
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader title="Logs" />
      <section
        aria-label="SQL not available"
        className="mx-5 my-3 flex max-w-2xl flex-col gap-2 rounded-card border border-border bg-surface p-4 text-sm"
      >
        <p>{AUDITOR_SQL_OFF}</p>
        <p className="flex gap-3">
          <button
            type="button"
            onClick={() => navigate("audit")}
            className="font-semibold text-accent-text hover:underline"
          >
            Open the audit log
          </button>
          <button
            type="button"
            onClick={() => navigate("dashboard")}
            className="font-semibold text-accent-text hover:underline"
          >
            Open dashboards
          </button>
        </p>
      </section>
    </div>
  );
}
