import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Field } from "@/features/auth/Field";
import { FormError } from "@/features/auth/FormError";
import { ApiError, api, type Source } from "@/lib/api";
import { CONTENT, Checklist, FEEDS, GRAPH } from "./ApiSourceFields";

interface ConnectorSettingsEditorProps {
  source: Source;
  onClose: () => void;
}

/** Change what an API or Loki source reads without touching its stored credential
 * (install finding F44): feeds, first-run history, the Loki query. The tenant, app,
 * cloud, key type, and Loki address go with the credential and stay as they are.
 * Audited source.settings_change with the old and new values. */
export function ConnectorSettingsEditor({ source, onClose }: ConnectorSettingsEditorProps) {
  const client = useQueryClient();
  const [m365, setM365] = useState(source.m365 ?? null);
  const [anthropic, setAnthropic] = useState(source.anthropic ?? null);
  const [loki, setLoki] = useState(source.loki ?? null);
  const save = useMutation({
    mutationFn: () => {
      const changes: Record<string, unknown> = m365
        ? {
            content_types: m365.content_types,
            graph: m365.graph,
            backfill_hours: m365.backfill_hours,
          }
        : anthropic
          ? { feeds: anthropic.feeds, backfill_days: anthropic.backfill_days }
          : { query: loki?.query, backfill_hours: loki?.backfill_hours };
      const before: Record<string, unknown> =
        (source.m365 as Record<string, unknown> | null | undefined) ??
        (source.anthropic as Record<string, unknown> | null | undefined) ??
        (source.loki as Record<string, unknown> | null | undefined) ??
        {};
      const changed = Object.fromEntries(
        Object.entries(changes).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(before[k])),
      );
      return api.setConnectorSettings(source.source_id, changed);
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["source-list"] });
      onClose();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };

  return (
    <form
      onSubmit={submit}
      aria-label={`Settings for ${source.source_id}`}
      className="flex flex-col gap-3 font-sans"
    >
      {m365 ? (
        <>
          <Checklist
            legend="Audit logs (Office 365 Management APIs)"
            items={CONTENT}
            value={m365.content_types}
            onChange={(v) => setM365({ ...m365, content_types: v })}
          />
          <Checklist
            legend="Microsoft Graph"
            items={GRAPH}
            value={m365.graph}
            onChange={(v) => setM365({ ...m365, graph: v })}
          />
          <Field
            label="Newly added feeds read back (hours)"
            help="At most 168. Feeds already reading continue where they are."
            type="number"
            min={0}
            max={168}
            value={m365.backfill_hours}
            onChange={(e) => setM365({ ...m365, backfill_hours: Number(e.target.value) })}
          />
        </>
      ) : null}
      {anthropic ? (
        <>
          <Checklist
            legend="Feeds"
            items={FEEDS}
            value={anthropic.feeds}
            onChange={(v) => setAnthropic({ ...anthropic, feeds: v })}
          />
          <Field
            label="Newly added feeds read back (days)"
            help="At most 31. Feeds already reading continue where they are."
            type="number"
            min={0}
            max={31}
            value={anthropic.backfill_days}
            onChange={(e) => setAnthropic({ ...anthropic, backfill_days: Number(e.target.value) })}
          />
        </>
      ) : null}
      {loki ? (
        <>
          <Field
            label="Query"
            help="A LogQL stream selector. Reading continues from the same point in time."
            value={loki.query}
            onChange={(e) => setLoki({ ...loki, query: e.target.value })}
            className="font-mono"
          />
        </>
      ) : null}
      <p className="text-sm text-text-muted">
        {loki
          ? "The stored sign-in is kept. To change the Loki address or sign-in, add a new source."
          : "The stored credential is kept. To change the tenant, app, cloud, or key type, use Replace credentials or add a new source."}
      </p>
      <FormError message={save.error instanceof ApiError ? save.error.message : null} />
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={save.isPending}
          className="h-8 rounded bg-accent px-3 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {save.isPending ? "Saving" : "Save"}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

interface ConnectorSettingsButtonProps {
  source: Source;
  canManage: boolean;
}

/** "Edit settings" under a connector source's summary, opening the editor in place. */
export function ConnectorSettingsButton({ source, canManage }: ConnectorSettingsButtonProps) {
  const [open, setOpen] = useState(false);
  if (!canManage) return null;
  if (open) return <ConnectorSettingsEditor source={source} onClose={() => setOpen(false)} />;
  return (
    <button
      type="button"
      onClick={() => setOpen(true)}
      aria-label={`Edit settings of ${source.source_id}`}
      className="self-start font-sans text-sm text-accent hover:underline"
    >
      Edit settings
    </button>
  );
}
