import type { RuleImportReport } from "@/lib/api";

interface RuleImportResultProps {
  report: RuleImportReport;
}

/** Counts of one rule import and the files it refused, with reasons. */
export function RuleImportResult({ report }: RuleImportResultProps) {
  const split = report.skipped !== undefined && report.not_compiling !== undefined;
  return (
    <div role="status" className="flex flex-col gap-2 text-sm">
      <div>
        {report.files} files read · {report.accepted} imported ({report.new_rules} new,{" "}
        {report.updated} updated, {report.unchanged} unchanged) ·{" "}
        {split
          ? `${report.skipped} skipped · ${report.not_compiling} not compiling`
          : `${report.refused} refused`}
        {report.truncated ? " · stopped early at an import limit" : ""}
      </div>
      {report.refusals.length ? (
        <div className="max-h-60 overflow-auto rounded border border-border">
          <table aria-label="Refused rules" className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
                <th className="px-2 py-1 font-semibold">File</th>
                <th className="px-2 py-1 font-semibold">Reason</th>
              </tr>
            </thead>
            <tbody>
              {report.refusals.map((r) => (
                <tr key={r.path} className="border-b border-border last:border-0">
                  <td className="px-2 py-1 font-mono">{r.path}</td>
                  <td className="px-2 py-1">{r.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
