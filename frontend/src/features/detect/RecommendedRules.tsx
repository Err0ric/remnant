import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { LevelBadge } from "./LevelBadge";
import { authorText, logsourceText } from "./rules";

const SHOWN = 50;

interface RecommendedRulesProps {
  isAdmin: boolean;
}

/** Imported rules that are off, compile, and match a source the viewer can read. Nothing is
 * enabled until an administrator clicks Enable. */
export function RecommendedRules({ isAdmin }: RecommendedRulesProps) {
  const client = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const list = useQuery({ queryKey: ["rules", "recommended"], queryFn: api.recommendedRules });
  const enable = useMutation({
    mutationFn: (ids: string[]) => api.setRulesEnabled(ids, true),
    onSuccess: async () => {
      setSelected(new Set());
      await client.invalidateQueries({ queryKey: ["rules"] });
    },
  });
  const rows = list.data ?? [];
  if (!rows.length) return null;
  const shown = rows.slice(0, SHOWN);
  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <section
      aria-label="Recommended rules for your sources"
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-surface-head px-3 py-1.5 text-sm">
        <span className="font-semibold">Recommended rules for your sources</span>
        <span className="text-text-secondary">
          {rows.length} {rows.length === 1 ? "rule" : "rules"} that are off and would run on your
          sources
        </span>
        {isAdmin ? (
          <button
            type="button"
            className="ml-auto rounded px-2 py-0.5 font-semibold text-accent-text hover:bg-surface disabled:opacity-40"
            onClick={() => enable.mutate([...selected])}
            disabled={!selected.size || enable.isPending}
          >
            Enable selected recommendations ({selected.size})
          </button>
        ) : null}
      </div>
      {enable.error ? (
        <p role="alert" className="px-3 py-1.5 text-sm text-danger">
          {enable.error instanceof ApiError ? enable.error.message : "That did not work"}
        </p>
      ) : null}
      <div className="max-h-80 overflow-y-auto">
        <table aria-label="Recommended rules" className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-text-secondary">
              {isAdmin ? <th className="w-8 px-3 py-1.5" aria-label="Select" /> : null}
              <th className="px-3 py-1.5 font-semibold">Title</th>
              <th className="px-3 py-1.5 font-semibold">Level</th>
              <th className="px-3 py-1.5 font-semibold">Log source</th>
              <th className="px-3 py-1.5 font-semibold">Would run on</th>
              <th className="px-3 py-1.5 font-semibold">ATT&amp;CK</th>
              {isAdmin ? <th className="px-3 py-1.5" aria-label="Actions" /> : null}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.rule_id} className="border-b border-border last:border-0">
                {isAdmin ? (
                  <td className="px-3 py-1">
                    <input
                      type="checkbox"
                      aria-label={`Select recommended ${r.title}`}
                      checked={selected.has(r.rule_id)}
                      onChange={() => toggle(r.rule_id)}
                    />
                  </td>
                ) : null}
                <td className="px-3 py-1 [overflow-wrap:anywhere]">
                  {r.title} <span className="text-text-muted">by {authorText(r.author)}</span>
                </td>
                <td className="px-3 py-1">
                  <LevelBadge level={r.level} />
                </td>
                <td className="px-3 py-1 font-mono text-text-secondary">{logsourceText(r)}</td>
                <td className="px-3 py-1 font-mono [overflow-wrap:anywhere]">
                  {r.source_ids.join(", ")}
                </td>
                <td className="px-3 py-1 font-mono text-text-secondary [overflow-wrap:anywhere]">
                  {r.attack_tags.length ? (
                    r.attack_tags.map((t) => t.replace(/^attack\./i, "")).join(", ")
                  ) : (
                    <span className="text-text-muted">·</span>
                  )}
                </td>
                {isAdmin ? (
                  <td className="whitespace-nowrap px-3 py-1 text-right">
                    <button
                      type="button"
                      className="rounded px-2 py-0.5 hover:bg-surface-head disabled:opacity-40"
                      onClick={() => enable.mutate([r.rule_id])}
                      disabled={enable.isPending}
                      aria-label={`Enable ${r.title}`}
                    >
                      Enable
                    </button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > SHOWN ? (
        <p className="border-t border-border px-3 py-1.5 text-sm text-text-secondary">
          Showing the {SHOWN} highest-level of {rows.length}.
        </p>
      ) : null}
    </section>
  );
}
