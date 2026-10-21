import { Fragment, useState } from "react";
import type { AuditEvent } from "@/lib/api";
import { describeAction } from "./actions";
import { OutcomeBadge } from "./OutcomeBadge";

interface ActivityTableProps {
  rows: AuditEvent[];
  onUser: (user: { id: string; name: string }) => void;
}

/** The activity log, newest first. Detail is shown as text, never interpreted. */
export function ActivityTable({ rows, onUser }: ActivityTableProps) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="overflow-x-auto">
      <table aria-label="Activity" className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-surface-head text-left text-text-secondary">
            <th className="w-8" />
            <th className="px-2 py-1.5 font-semibold">Time (UTC)</th>
            <th className="px-2 py-1.5 font-semibold">User</th>
            <th className="px-2 py-1.5 font-semibold">Action</th>
            <th className="px-2 py-1.5 font-semibold">Outcome</th>
            <th className="px-2 py-1.5 font-semibold">Address</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <Fragment key={r.audit_id}>
              <tr className="border-b border-border hover:bg-surface-head">
                <td className="px-2">
                  <button
                    type="button"
                    aria-expanded={open === r.audit_id}
                    aria-label={`Details of ${describeAction(r.action)} at ${r.ts}`}
                    onClick={() => setOpen(open === r.audit_id ? null : r.audit_id)}
                    className="text-text-muted hover:text-text"
                  >
                    {open === r.audit_id ? "▾" : "▸"}
                  </button>
                </td>
                <td className="whitespace-nowrap px-2 py-1 font-mono tabular-nums">
                  {r.ts.slice(0, 19).replace("T", " ")}
                </td>
                <td className="px-2 py-1">
                  {r.user_id ? (
                    <button
                      type="button"
                      onClick={() =>
                        onUser({ id: r.user_id ?? "", name: r.username ?? r.user_id ?? "" })
                      }
                      className="text-accent-text hover:underline"
                    >
                      {r.username ?? r.user_id}
                    </button>
                  ) : (
                    <span className="text-text-muted">none</span>
                  )}
                </td>
                <td className="px-2 py-1">
                  <span className="text-text">{describeAction(r.action)}</span>{" "}
                  <span className="font-mono text-xs font-normal text-text-muted">{r.action}</span>
                </td>
                <td className="px-2 py-1">
                  <OutcomeBadge outcome={r.outcome} />
                </td>
                <td className="px-2 py-1 font-mono text-text-secondary">{r.ip ?? ""}</td>
              </tr>
              {open === r.audit_id ? (
                <tr className="border-b border-border bg-surface-expand">
                  <td />
                  <td colSpan={5} className="px-2 py-2">
                    <pre className="m-0 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded border border-border bg-inset px-3 py-2 font-mono text-sm">
                      {JSON.stringify(r.detail, null, 2)}
                    </pre>
                  </td>
                </tr>
              ) : null}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
