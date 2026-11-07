import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";
import { RuleImportResult } from "./RuleImportResult";

interface SigmaHqImportPanelProps {
  onClose: () => void;
}

/** Admin: import the SigmaHQ core rules from the pinned release, downloaded only on this
 * click and checked against its SHA-256, or from an uploaded zip (D211). Rules start
 * disabled. */
export function SigmaHqImportPanel({ onClose }: SigmaHqImportPanelProps) {
  const client = useQueryClient();
  const release = useQuery({ queryKey: ["rules", "sigmahq"], queryFn: api.sigmaHqRelease });
  const done = () => client.invalidateQueries({ queryKey: ["rules"] });
  const fetchRun = useMutation({ mutationFn: api.importSigmaHq, onSuccess: done });
  const upload = useMutation({ mutationFn: api.importRulesZip, onSuccess: done });
  const pending = fetchRun.isPending || upload.isPending;
  const last = upload.submittedAt > fetchRun.submittedAt ? upload : fetchRun;
  const tag = release.data?.release;

  return (
    <section
      aria-label="Import SigmaHQ core rules"
      className="flex flex-col gap-2 rounded-card border border-border bg-surface p-3"
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold">SigmaHQ core rules</span>
        {tag ? (
          <span className="text-text-secondary">
            release <span className="font-mono">{tag}</span>
          </span>
        ) : null}
        <button
          type="button"
          className="ml-auto h-8 rounded border border-border px-3 font-semibold text-accent-text hover:bg-surface-head disabled:opacity-40"
          onClick={() => fetchRun.mutate()}
          disabled={pending || !tag}
        >
          {fetchRun.isPending ? "Downloading…" : `Download and import ${tag ?? ""}`.trim()}
        </button>
        <button type="button" className="h-8 rounded px-3 hover:bg-surface-head" onClick={onClose}>
          Close
        </button>
      </div>
      <p className="text-sm text-text-secondary">
        The server downloads the pinned package from GitHub once, on this click, and imports it only
        if its SHA-256 matches
        {release.data ? (
          <>
            {" "}
            (<span className="font-mono break-all">{release.data.sha256}</span>)
          </>
        ) : null}
        . Imported rules start disabled. Without internet access, upload the same{" "}
        <span className="font-mono">{release.data?.asset ?? "sigma_core.zip"}</span> instead.
      </p>
      <label className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-text-secondary">Or upload a rule package (zip)</span>
        <input
          type="file"
          accept=".zip,application/zip"
          disabled={pending}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload.mutate(file);
            e.target.value = "";
          }}
        />
      </label>
      {last.error ? (
        <p role="alert" className="text-sm text-danger">
          {last.error instanceof ApiError ? last.error.message : "The import did not work"}
        </p>
      ) : null}
      {last.data ? <RuleImportResult report={last.data} /> : null}
    </section>
  );
}
