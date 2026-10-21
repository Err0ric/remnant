import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { FormError } from "@/features/auth/FormError";
import { ApiCredentialsFields } from "./ApiCredentialsFields";
import { ApiError, api, type ApiCredentials, type Source } from "@/lib/api";

function lag(seconds: number): string {
  if (seconds < 3 * 3600) return "up to date";
  if (seconds < 2 * 86400) return `${Math.round(seconds / 3600)} h behind`;
  return `${Math.round(seconds / 86400)} days behind`;
}

interface ApiSummaryProps {
  source: Source;
  canManage: boolean;
}

/** What a Microsoft 365 or Anthropic source reads, how far behind it is, and a way to
 * replace its credentials (a renewed certificate or a new key). */
export function ApiSummary({ source, canManage }: ApiSummaryProps) {
  const client = useQueryClient();
  const kind = source.kind === "m365" ? "m365" : "anthropic";
  const [open, setOpen] = useState(false);
  const [creds, setCreds] = useState<ApiCredentials>({});
  const replace = useMutation({
    mutationFn: () => api.replaceCredentials(source.source_id, creds),
    onSuccess: async () => {
      setOpen(false);
      setCreds({});
      await client.invalidateQueries({ queryKey: ["source-list"] });
    },
  });
  const feeds =
    kind === "m365"
      ? [...(source.m365?.content_types ?? []), ...(source.m365?.graph ?? [])]
      : (source.anthropic?.feeds ?? []);
  const behind = source.status.behind_s ?? null;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    replace.mutate();
  };

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-badge bg-sev-info-bg px-2 py-px font-sans text-xs text-text-secondary">
          {kind === "m365" ? "Microsoft 365" : "Anthropic"}
        </span>
        {source.m365 ? <span className="break-all">{source.m365.tenant_id}</span> : null}
      </div>
      {feeds.length ? (
        <div className="break-words text-sm text-text-secondary">{feeds.join(", ")}</div>
      ) : null}
      {behind !== null ? <div className="text-sm text-text-muted">{lag(behind)}</div> : null}
      {canManage && !open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="self-start font-sans text-sm text-accent hover:underline"
        >
          Replace credentials
        </button>
      ) : null}
      {open ? (
        <form
          onSubmit={submit}
          aria-label={`Replace credentials for ${source.source_id}`}
          className="flex flex-col gap-2 font-sans"
        >
          <ApiCredentialsFields
            kind={kind}
            auth={source.m365?.auth}
            value={creds}
            onChange={setCreds}
          />
          <FormError message={replace.error instanceof ApiError ? replace.error.message : null} />
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={replace.isPending}
              className="h-8 rounded bg-accent px-3 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
            >
              {replace.isPending ? "Saving" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setCreds({});
              }}
              className="h-8 rounded border border-border-strong px-3 text-sm hover:bg-surface-head"
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
