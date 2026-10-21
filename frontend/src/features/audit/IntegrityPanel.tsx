import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { since, stamp } from "@/features/overview/time";
import { ApiError, api, type IntegritySeal } from "@/lib/api";

const STATUS: Record<IntegritySeal["status"], { label: string; badge: string; bar: string }> = {
  verified: { label: "Verified", badge: "bg-local-bg text-local-text", bar: "bg-ok" },
  warnings: { label: "Warnings", badge: "bg-sev-medium-bg text-sev-medium-text", bar: "bg-warn" },
  failed: { label: "Failed", badge: "bg-sev-critical-bg text-sev-critical-text", bar: "bg-danger" },
};

const KIND: Record<string, string> = {
  changed: "Changed",
  missing: "Missing",
  chain_broken: "Ledger edited",
  audit_changed: "Audit row edited",
  unknown: "Not recorded",
  removal_pending: "Removal pending",
  adopted: "Adopted lately",
  stray: "Outside the layout",
  seal_mismatch: "Differs from a seal",
};

function save(text: string, name: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function every(seconds: number): string {
  if (seconds % 86400 === 0) return seconds === 86400 ? "daily" : `every ${seconds / 86400} days`;
  if (seconds % 3600 === 0) return `every ${seconds / 3600} h`;
  return `every ${Math.round(seconds / 60)} min`;
}

function Head({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 items-baseline gap-2">
      <dt className="w-24 shrink-0 text-xs uppercase tracking-wide text-text-muted">{label}</dt>
      <dd className="min-w-0 truncate font-mono text-xs text-text" title={value}>
        {value}
      </dd>
    </div>
  );
}

interface IntegrityPanelProps {
  isAdmin: boolean;
}

/** Log integrity (ADR-0022): the lake ledger and audit chain, checked and sealed. */
export function IntegrityPanel({ isAdmin }: IntegrityPanelProps) {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["integrity"], queryFn: api.integrity });
  const targets = useQuery({
    queryKey: ["alert-targets"],
    queryFn: api.alertTargets,
    enabled: isAdmin,
  });
  const verify = useMutation({
    mutationFn: api.verifyIntegrity,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["integrity"] }),
  });
  const report = useMutation({
    mutationFn: async () => {
      const body = await api.integrityReport(30);
      save(
        JSON.stringify(body, null, 2),
        `integrity-report-${new Date().toISOString().slice(0, 10)}.json`,
      );
    },
  });
  const [draft, setDraft] = useState<{ target_ids: string[]; send_seals: boolean } | null>(null);
  const settings = useMutation({
    mutationFn: api.saveIntegritySettings,
    onSuccess: () => {
      setDraft(null);
      void qc.invalidateQueries({ queryKey: ["integrity"] });
    },
  });

  const data = status.data;
  const latest = data?.latest ?? null;
  const now = new Date().toISOString();
  const chosen = draft ?? data?.settings ?? { target_ids: [], send_seals: false };
  // A check that ran moments ago is not an error: say so quietly (409 from the server).
  const busy = verify.error instanceof ApiError && verify.error.status === 409;
  const error = status.error ?? (busy ? null : verify.error) ?? report.error ?? settings.error;
  const findings = latest?.findings ?? [];
  const history = [...(data?.history ?? [])].reverse();

  return (
    <div className="flex flex-col gap-3 px-5 pb-5">
      {busy ? (
        <p role="status" className="text-sm text-text-secondary">
          {(verify.error as ApiError).message}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error instanceof ApiError ? error.message : "Could not load the integrity status"}
        </p>
      ) : null}

      <section
        aria-label="Integrity status"
        className="flex flex-col gap-3 rounded border border-border bg-surface p-3"
      >
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {latest ? (
            <span
              className={`rounded px-2 py-0.5 text-sm font-semibold ${STATUS[latest.status].badge}`}
            >
              {STATUS[latest.status].label}
            </span>
          ) : (
            <span className="rounded bg-surface-head px-2 py-0.5 text-sm text-text-secondary">
              Not checked yet
            </span>
          )}
          <span className="text-sm text-text-secondary">
            {latest
              ? `Checked ${since(latest.at, now)} (${stamp(latest.at)} UTC)`
              : status.isPending
                ? "Loading…"
                : "The first check runs shortly after start"}
            {data ? ` · runs ${every(data.interval_s)}` : ""}
          </span>
          <span className="ml-auto flex gap-1">
            {isAdmin ? (
              <button
                type="button"
                onClick={() => verify.mutate()}
                disabled={verify.isPending}
                className="h-8 rounded px-3 text-sm font-semibold text-accent-text hover:bg-surface-head disabled:opacity-40"
              >
                {verify.isPending ? "Checking…" : "Verify now"}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => report.mutate()}
              disabled={report.isPending || !latest}
              className="h-8 rounded px-3 text-sm text-text hover:bg-surface-head disabled:opacity-40"
            >
              {report.isPending ? "Preparing…" : "Download report"}
            </button>
          </span>
        </div>

        {latest ? (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-4">
            {(
              [
                ["Files verified", latest.files],
                ["Ledger entries", latest.lake_seq],
                ["Audit rows", latest.audit_rows],
                ["Problems", latest.failures + latest.warnings],
              ] as const
            ).map(([label, value]) => (
              <div key={label} className="flex flex-col">
                <dt className="text-xs uppercase tracking-wide text-text-muted">{label}</dt>
                <dd className="font-mono text-lg tabular-nums text-text">
                  {value.toLocaleString()}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}

        {latest ? (
          <dl className="flex flex-col gap-0.5 border-t border-border pt-2">
            <Head label="Lake head" value={latest.lake_head} />
            <Head label="Audit head" value={latest.audit_head} />
            {latest.llm_head ? (
              <Head
                label="AI calls"
                value={`${latest.llm_head} (${latest.llm_rows.toLocaleString()} records)`}
              />
            ) : null}
            <Head
              label="Seal"
              value={`#${latest.seal_id} ${latest.signature}${latest.signature_ok ? "" : " (signature does not match)"}`}
            />
          </dl>
        ) : null}

        {history.length > 1 ? (
          <div className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-wide text-text-muted">Last 30 days</span>
            <ol aria-label="Recent checks" className="flex h-5 items-stretch gap-px">
              {history.map((s) => (
                <li
                  key={s.seal_id}
                  title={`${stamp(s.at)} UTC · ${STATUS[s.status].label}`}
                  className={`w-1.5 rounded-sm ${STATUS[s.status].bar}`}
                >
                  <span className="sr-only">
                    {stamp(s.at)} {STATUS[s.status].label}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ) : null}
      </section>

      {findings.length > 0 ? (
        <section aria-label="Findings" className="rounded border border-border bg-surface">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-head text-left text-xs uppercase tracking-wide text-text-muted">
                <tr>
                  <th className="px-3 py-1.5 font-medium">Finding</th>
                  <th className="px-3 py-1.5 font-medium">Where</th>
                  <th className="px-3 py-1.5 font-medium">Detail</th>
                </tr>
              </thead>
              <tbody>
                {findings.map((f, i) => (
                  <tr key={`${f.path}-${i}`} className="border-t border-border">
                    <td
                      className={`whitespace-nowrap px-3 py-1.5 ${
                        f.severity === "failure" ? "text-danger" : "text-warn"
                      }`}
                    >
                      {KIND[f.kind] ?? f.kind}
                    </td>
                    <td className="px-3 py-1.5 font-mono text-xs text-text">{f.path}</td>
                    <td className="px-3 py-1.5 text-text-secondary">{f.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {isAdmin ? (
        <section
          aria-label="Integrity alerts"
          className="flex flex-col gap-2 rounded border border-border bg-surface p-3"
        >
          <h3 className="text-sm font-semibold text-text">Alerts and off-server seals</h3>
          <p className="max-w-prose text-sm text-text-secondary">
            Failed checks go to the targets below. A daily seal sends both chain heads too, so a
            copy lives outside this server: keep those messages.
          </p>
          {targets.data && targets.data.length > 0 ? (
            <fieldset className="flex flex-wrap gap-x-4 gap-y-1">
              <legend className="sr-only">Alert targets</legend>
              {targets.data.map((t) => (
                <label key={t.target_id} className="flex items-center gap-1.5 text-sm text-text">
                  <input
                    type="checkbox"
                    checked={chosen.target_ids.includes(t.target_id)}
                    onChange={(e) =>
                      setDraft({
                        ...chosen,
                        target_ids: e.target.checked
                          ? [...chosen.target_ids, t.target_id]
                          : chosen.target_ids.filter((x) => x !== t.target_id),
                      })
                    }
                  />
                  {t.name}
                </label>
              ))}
            </fieldset>
          ) : (
            <p className="text-sm text-text-muted">
              No alert targets yet. Add one under Settings, Alert targets.
            </p>
          )}
          <label className="flex items-center gap-1.5 text-sm text-text">
            <input
              type="checkbox"
              checked={chosen.send_seals}
              onChange={(e) => setDraft({ ...chosen, send_seals: e.target.checked })}
            />
            Send a daily seal to these targets
          </label>
          <div>
            <button
              type="button"
              onClick={() => settings.mutate(chosen)}
              disabled={draft === null || settings.isPending}
              className="h-8 rounded border border-border px-3 text-sm text-text hover:bg-surface-head disabled:opacity-40"
            >
              {settings.isPending ? "Saving…" : "Save"}
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
