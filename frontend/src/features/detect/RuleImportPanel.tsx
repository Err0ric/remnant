import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";

interface RuleImportPanelProps {
  onClose: () => void;
}

/** Admin: import a rule file or folder under the server's rule folders (ADR-0006). */
export function RuleImportPanel({ onClose }: RuleImportPanelProps) {
  const client = useQueryClient();
  const [path, setPath] = useState("/rules/sigma/rules");
  const run = useMutation({
    mutationFn: () => api.importRules(path.trim()),
    onSuccess: () => client.invalidateQueries({ queryKey: ["rules"] }),
  });
  const report = run.data;

  return (
    <section
      aria-label="Import rules"
      className="flex flex-col gap-2 rounded-card border border-border bg-surface p-3"
    >
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (path.trim()) run.mutate();
        }}
      >
        <label className="flex min-w-0 flex-[1_1_320px] flex-col gap-1 text-sm">
          <span className="text-text-secondary">Rule file or folder on the server</span>
          <input
            className="h-8 rounded border border-border bg-inset px-2 font-mono"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            spellCheck={false}
          />
        </label>
        <button
          type="submit"
          className="h-8 rounded border border-border px-3 font-semibold text-accent-text hover:bg-surface-head disabled:opacity-40"
          disabled={run.isPending || !path.trim()}
        >
          {run.isPending ? "Importing…" : "Import"}
        </button>
        <button type="button" className="h-8 rounded px-3 hover:bg-surface-head" onClick={onClose}>
          Close
        </button>
      </form>
      <p className="text-sm text-text-secondary">
        Rules are read from the folders the server allows for rules (for example a copy of SigmaHQ
        in <span className="font-mono">/rules</span>). Each import is a pinned snapshot; new rules
        start disabled. A large folder takes about a minute.
      </p>
      {run.error ? (
        <p role="alert" className="text-sm text-danger">
          {run.error instanceof ApiError ? run.error.message : "The import did not work"}
        </p>
      ) : null}
      {report ? (
        <div role="status" className="flex flex-col gap-2 text-sm">
          <div>
            {report.files} files read · {report.accepted} accepted ({report.new_rules} new,{" "}
            {report.updated} updated, {report.unchanged} unchanged) · {report.refused} refused
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
      ) : null}
    </section>
  );
}
