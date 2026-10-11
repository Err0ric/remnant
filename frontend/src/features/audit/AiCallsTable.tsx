import { Fragment, useState } from "react";
import type { AuditLlmCall } from "@/lib/api";
import { OutcomeBadge } from "./OutcomeBadge";

interface AiCallsTableProps {
  rows: AuditLlmCall[];
  onUser: (user: { id: string; name: string }) => void;
}

function result(c: AuditLlmCall): { outcome: string; label: string } {
  if (c.classification_result === "blocked") return { outcome: "blocked", label: "Blocked" };
  if (c.error) return { outcome: "failure", label: c.error };
  if (!c.finished_at) return { outcome: "denied", label: "Not finished" };
  return { outcome: "success", label: "Answered" };
}

/** Every model call (SPEC 6.4): who, which model, what scope, and how it ended. */
export function AiCallsTable({ rows, onUser }: AiCallsTableProps) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="overflow-x-auto">
      <table aria-label="AI calls" className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
            <th className="w-8" />
            <th className="px-2 py-1.5 font-semibold">Time (UTC)</th>
            <th className="px-2 py-1.5 font-semibold">User</th>
            <th className="px-2 py-1.5 font-semibold">Purpose</th>
            <th className="px-2 py-1.5 font-semibold">Model</th>
            <th className="px-2 py-1.5 font-semibold">Result</th>
            <th className="px-2 py-1.5 text-right font-semibold">Tokens in / out</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const res = result(c);
            return (
              <Fragment key={c.call_id}>
                <tr className="border-b border-border hover:bg-surface-head">
                  <td className="px-2">
                    <button
                      type="button"
                      aria-expanded={open === c.call_id}
                      aria-label={`Details of the ${c.purpose} call at ${c.ts}`}
                      onClick={() => setOpen(open === c.call_id ? null : c.call_id)}
                      className="text-text-muted hover:text-text"
                    >
                      {open === c.call_id ? "▾" : "▸"}
                    </button>
                  </td>
                  <td className="whitespace-nowrap px-2 py-1 font-mono tabular-nums">
                    {c.ts.slice(0, 19).replace("T", " ")}
                  </td>
                  <td className="px-2 py-1">
                    <button
                      type="button"
                      onClick={() => onUser({ id: c.user_id, name: c.username ?? c.user_id })}
                      className="text-accent-text hover:underline"
                    >
                      {c.username ?? c.user_id}
                    </button>
                  </td>
                  <td className="px-2 py-1 font-mono">{c.purpose}</td>
                  <td className="px-2 py-1">
                    <span className="mr-2 font-mono">{c.model}</span>
                    <span
                      className={`rounded-badge px-2 py-px text-xs ${c.locality === "local" ? "bg-local-bg text-local-text" : "bg-cloud-bg text-cloud-text"}`}
                    >
                      {c.locality === "local" ? "Local" : "Cloud"}
                    </span>
                  </td>
                  <td className="px-2 py-1">
                    <OutcomeBadge outcome={res.outcome} label={res.label} />
                  </td>
                  <td className="px-2 py-1 text-right font-mono tabular-nums">
                    {c.prompt_tokens ?? "·"} / {c.completion_tokens ?? "·"}
                  </td>
                </tr>
                {open === c.call_id ? (
                  <tr className="border-b border-border bg-surface-expand">
                    <td />
                    <td colSpan={6} className="px-2 py-2">
                      <dl className="m-0 grid grid-cols-[160px_minmax(0,1fr)] gap-x-3 gap-y-1">
                        {(
                          [
                            ["Call id", c.call_id],
                            ["Provider", c.provider_id],
                            ["Prompt", c.prompt_ref],
                            ["Sources in scope", c.sources_in_scope.join(", ") || "none"],
                            [
                              "Redaction",
                              c.redaction_applied
                                ? `Applied (${
                                    Object.entries(c.redaction_counts ?? {})
                                      .map(([k, n]) => `${n} ${k}`)
                                      .join(", ") || "nothing found"
                                  })`
                                : "Not applied",
                            ],
                            ["Citation check", c.citation_check ?? "not applicable"],
                            ["Latency", c.latency_ms === null ? "·" : `${c.latency_ms} ms`],
                            ["Prompt sha256", c.prompt_sha256 ?? "·"],
                            ["Response sha256", c.response_sha256 ?? "·"],
                          ] as const
                        ).map(([k, v]) => (
                          <Fragment key={k}>
                            <dt className="text-text-secondary">{k}</dt>
                            <dd className="m-0 break-all font-mono">{v}</dd>
                          </Fragment>
                        ))}
                      </dl>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
