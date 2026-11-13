import { Skeleton } from "@/components/Skeleton";
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";
import { SectionTitle } from "@/components/SectionTitle";

interface Draft {
  enabled: boolean;
  at_time: string;
  keep: string;
}

/** Scheduled backups (handoff item 8): on or off, the daily time, and how many are kept.
 * Administrators only; every change is audited on the server. */
export function BackupSettings() {
  const client = useQueryClient();
  const current = useQuery({ queryKey: ["backup-settings"], queryFn: api.backupSettings });
  const [draft, setDraft] = useState<Draft | null>(null);
  const save = useMutation({
    mutationFn: api.setBackupSettings,
    onSuccess: (data) => {
      client.setQueryData(["backup-settings"], data);
      void client.invalidateQueries({ queryKey: ["health-checks"] });
      setDraft(null);
    },
  });
  const c = current.data;
  const value: Draft = draft ?? {
    enabled: c?.enabled ?? true,
    at_time: c?.at_time ?? "",
    keep: String(c?.keep ?? ""),
  };
  const keep = Number(value.keep);
  const valid =
    /^([01]\d|2[0-3]):[0-5]\d$/.test(value.at_time) &&
    Number.isInteger(keep) &&
    keep >= 1 &&
    keep <= 90;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (valid) save.mutate({ enabled: value.enabled, at_time: value.at_time, keep });
  };
  return (
    <section aria-label="Backups" className="flex flex-col gap-1">
      <SectionTitle>Backups</SectionTitle>
      <p className="text-text-secondary">
        A backup of events, settings, users, the audit log, and the key that unlocks stored secrets,
        every day. The oldest beyond the count are deleted only after a new backup succeeds. Health
        shows the last one.
      </p>
      {c ? (
        <p className="text-text-secondary">
          Folder <span className="font-mono">{c.folder}</span>. Copy it off this server too.
        </p>
      ) : null}
      {/* The form waits for the saved settings: an edit made before they load would save
          an empty time (and Save would stay disabled). */}
      {!c && !current.isError ? (
        <Skeleton label="the backup settings" rows={1} />
      ) : !c ? (
        <p className="text-text-muted">Could not load the settings.</p>
      ) : (
        <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={value.enabled}
              onChange={(e) => setDraft({ ...value, enabled: e.target.checked })}
            />
            Back up daily at
          </label>
          <input
            aria-label="Time of day"
            type="time"
            value={value.at_time}
            onChange={(e) => setDraft({ ...value, at_time: e.target.value })}
            className="h-8 rounded border border-border-control bg-surface px-2 font-mono tabular-nums"
          />
          <span className="text-text-secondary">{c.timezone}, keep</span>
          <input
            aria-label="Backups kept"
            inputMode="numeric"
            value={value.keep}
            onChange={(e) => setDraft({ ...value, keep: e.target.value })}
            className="h-8 w-14 rounded border border-border-control bg-surface px-2 tabular-nums"
          />
          <span className="text-text-secondary">(1 to 90)</span>
          <button
            type="submit"
            disabled={save.isPending || draft === null || !valid}
            className="h-8 rounded bg-accent px-3 font-semibold text-white disabled:opacity-50"
          >
            Save
          </button>
          {save.isError ? (
            <span role="alert" className="text-danger">
              {save.error instanceof ApiError ? save.error.message : "Could not save."}
            </span>
          ) : null}
        </form>
      )}
    </section>
  );
}
