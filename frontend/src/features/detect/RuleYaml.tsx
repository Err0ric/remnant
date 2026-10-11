import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { authorText } from "./rules";

interface RuleYamlProps {
  ruleId: string;
  onClose: () => void;
}

/** The pinned YAML of a rule, as imported. Rendered as text, never as markup. */
export function RuleYaml({ ruleId, onClose }: RuleYamlProps) {
  const rule = useQuery({ queryKey: ["rule", ruleId], queryFn: () => api.rule(ruleId) });
  return (
    <section
      aria-label="Rule source"
      className="flex flex-col gap-2 rounded-card border border-border bg-surface p-3 text-sm"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{rule.data?.title ?? "Rule"}</span>
        {rule.data ? (
          <span className="text-text-secondary">by {authorText(rule.data.author)}</span>
        ) : null}
        <button
          type="button"
          className="ml-auto rounded px-2 py-1 hover:bg-surface-head"
          onClick={onClose}
        >
          Close
        </button>
      </div>
      {rule.data ? (
        <>
          <div className="font-mono text-text-muted">
            {rule.data.path} · sha256 {rule.data.sha256.slice(0, 16)}
          </div>
          <pre className="max-h-96 overflow-auto rounded border border-border bg-inset p-2 font-mono text-sm">
            {rule.data.yaml}
          </pre>
        </>
      ) : null}
    </section>
  );
}
