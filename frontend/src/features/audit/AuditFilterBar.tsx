import { X } from "lucide-react";
import type { AuditFilters } from "@/lib/api";

export type AuditRange = "24h" | "7d" | "30d" | "all";
export type AuditLog = "activity" | "ai";

export interface AuditFilterState {
  text: string; // an action prefix (activity) or a purpose (AI calls)
  outcome: AuditFilters["outcome"] | "";
  range: AuditRange;
  user: { id: string; name: string } | null;
}

const RANGES: { id: AuditRange; label: string; ms: number | null }[] = [
  { id: "24h", label: "Last 24 hours", ms: 86_400_000 },
  { id: "7d", label: "Last 7 days", ms: 7 * 86_400_000 },
  { id: "30d", label: "Last 30 days", ms: 30 * 86_400_000 },
  { id: "all", label: "All time", ms: null },
];
const PURPOSES = ["ask", "explain", "report", "parser_draft"];

/** The filters as the API takes them. */
export function toApiFilters(f: AuditFilterState): AuditFilters {
  const ms = RANGES.find((r) => r.id === f.range)?.ms ?? null;
  return {
    action: f.text.trim() || undefined,
    outcome: f.outcome || undefined,
    user_id: f.user?.id,
    since: ms ? new Date(Date.now() - ms).toISOString() : undefined,
  };
}

interface AuditFilterBarProps {
  log: AuditLog;
  value: AuditFilterState;
  onChange: (next: AuditFilterState) => void;
}

const SELECT =
  "h-8 rounded border border-border-strong bg-surface px-2 text-sm focus:outline-none focus:ring-2 focus:ring-focus-ring";

export function AuditFilterBar({ log, value, onChange }: AuditFilterBarProps) {
  const set = (patch: Partial<AuditFilterState>) => onChange({ ...value, ...patch });
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      {log === "activity" ? (
        <label className="flex items-center gap-2">
          <span className="text-text-secondary">Action</span>
          <input
            value={value.text}
            onChange={(e) => set({ text: e.target.value })}
            placeholder="query. or user.login"
            maxLength={100}
            spellCheck={false}
            className={`${SELECT} w-48 font-mono`}
          />
        </label>
      ) : (
        <label className="flex items-center gap-2">
          <span className="text-text-secondary">Purpose</span>
          <select
            value={value.text}
            onChange={(e) => set({ text: e.target.value })}
            className={SELECT}
          >
            <option value="">Any</option>
            {PURPOSES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="flex items-center gap-2">
        <span className="text-text-secondary">Outcome</span>
        <select
          value={value.outcome}
          onChange={(e) => set({ outcome: e.target.value as AuditFilterState["outcome"] })}
          className={SELECT}
        >
          <option value="">Any</option>
          <option value="success">Success</option>
          <option value="failure">Failure</option>
          {log === "activity" ? (
            <option value="denied">Denied</option>
          ) : (
            <option value="blocked">Blocked by classification</option>
          )}
        </select>
      </label>
      <label className="flex items-center gap-2">
        <span className="text-text-secondary">Time</span>
        <select
          value={value.range}
          onChange={(e) => set({ range: e.target.value as AuditRange })}
          className={SELECT}
        >
          {RANGES.map((r) => (
            <option key={r.id} value={r.id}>
              {r.label}
            </option>
          ))}
        </select>
      </label>
      {value.user ? (
        <span className="flex items-center gap-1 rounded-chip bg-accent-subtle py-0.5 pl-2.5 pr-1.5 text-accent-text">
          User: {value.user.name}
          <button
            type="button"
            aria-label={`Remove user filter ${value.user.name}`}
            onClick={() => set({ user: null })}
            className="rounded-full p-0.5 hover:bg-white/10"
          >
            <X size={12} aria-hidden />
          </button>
        </span>
      ) : (
        <span className="text-text-muted">Click a user in the list to filter by them</span>
      )}
    </div>
  );
}
