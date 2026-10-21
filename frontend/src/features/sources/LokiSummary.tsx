import type { LokiSettings } from "@/lib/api";

interface LokiSummaryProps {
  /** Null for viewers who are not administrators: the address is withheld. */
  loki: LokiSettings | null;
  behind: number | null;
}

function hostOf(url: string): string {
  try {
    return url ? new URL(url).host : "";
  } catch {
    return url; // shown as typed when it does not parse
  }
}

function lag(seconds: number): string {
  if (seconds < 120) return "up to date";
  if (seconds < 7200) return `${Math.round(seconds / 60)} min behind`;
  return `${Math.round(seconds / 3600)} h behind`;
}

/** Where a Loki source reads from, and how far behind it is (ADR-0011). */
export function LokiSummary({ loki, behind }: LokiSummaryProps) {
  const host = hostOf(loki?.url ?? "");
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-badge bg-sev-info-bg px-2 py-px text-xs font-normal text-text-secondary">
          Loki
        </span>
        {host ? <span>{host}</span> : null}
      </div>
      {loki ? <div className="break-all text-sm text-text-secondary">{loki.query}</div> : null}
      {behind !== null ? <div className="text-sm text-text-muted">{lag(behind)}</div> : null}
    </div>
  );
}
