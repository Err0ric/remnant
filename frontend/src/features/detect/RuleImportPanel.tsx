import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { RuleImportResult } from "./RuleImportResult";

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
      {report ? <RuleImportResult report={report} /> : null}
    </section>
  );
}
