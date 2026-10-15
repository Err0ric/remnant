import type { AiStatus } from "@/lib/api";

const STYLE: Record<AiStatus, string> = {
  approved: "bg-local-bg text-local-text",
  not_approved: "bg-sev-critical-bg text-sev-critical-text",
  unreviewed: "bg-surface-head text-text-secondary",
};
export const STATUS_LABEL: Record<AiStatus, string> = {
  approved: "Approved",
  not_approved: "Not approved",
  unreviewed: "Unreviewed",
};

/** Review status of an AI service or MCP server; text, never color alone. */
export function StatusBadge({ status }: { status: AiStatus }) {
  return (
    <span className={`whitespace-nowrap rounded-badge px-1.5 py-px text-sm ${STYLE[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}

interface StatusPickerProps {
  label: string;
  value: AiStatus;
  onChange: (status: AiStatus) => void;
}

/** Admins set the review status inline; the change is audited server-side. */
export function StatusPicker({ label, value, onChange }: StatusPickerProps) {
  return (
    <select
      aria-label={`Review status of ${label}`}
      value={value}
      onChange={(e) => onChange(e.target.value as AiStatus)}
      className={`h-7 rounded border border-border-strong px-1.5 text-sm ${STYLE[value]}`}
    >
      {(Object.keys(STATUS_LABEL) as AiStatus[]).map((s) => (
        <option key={s} value={s}>
          {STATUS_LABEL[s]}
        </option>
      ))}
    </select>
  );
}
