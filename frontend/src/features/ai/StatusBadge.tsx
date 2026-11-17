import type { AiStatus } from "@/lib/api";
import { Select } from "@/components/forms/Select";

// A dot and the label (DESIGN.md 7). Never a severity color: Not approved is a review
// state, not an alert.
const DOT: Record<AiStatus, string> = {
  approved: "bg-local-tx",
  not_approved: "border-[1.5px] border-warn",
  unreviewed: "border-[1.5px] border-accent-text",
};
export const STATUS_LABEL: Record<AiStatus, string> = {
  approved: "Approved",
  not_approved: "Not approved",
  unreviewed: "Unreviewed",
};

/** Review status of an AI service or MCP server; text, never color alone. */
export function StatusBadge({ status }: { status: AiStatus }) {
  return (
    <span
      data-ai-status={status}
      className="inline-flex items-center gap-1.5 whitespace-nowrap text-text"
    >
      <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[status]}`} aria-hidden />
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
    <Select
      aria-label={`Review status of ${label}`}
      value={value}
      onChange={(v) => onChange(v as AiStatus)}
      options={(Object.keys(STATUS_LABEL) as AiStatus[]).map((s) => ({
        value: s,
        label: STATUS_LABEL[s],
      }))}
      className="h-7 text-sm"
    />
  );
}
