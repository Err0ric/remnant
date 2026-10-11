import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Field } from "@/features/auth/Field";
import { LokiFields } from "./LokiFields";
import { ParserSelect } from "./ParserSelect";
import { AUTO_PARSER, parserHelp } from "@/lib/parsers";
import { FormError } from "@/features/auth/FormError";
import { ApiError, api, type LokiSettings, type SourceFormat, type SourceInput } from "@/lib/api";

const ID_PATTERN = /^[a-z0-9][a-z0-9_]{0,63}$/;

const FORMATS: SourceFormat[] = ["syslog", "json", "csv"];

interface AddSourceFormProps {
  allowedRoots: string[];
  /** Values to start from, e.g. a discovery suggestion. The admin can change them all. */
  initial?: Partial<SourceInput>;
  onDone: () => void;
}

export function AddSourceForm({ allowedRoots, initial, onDone }: AddSourceFormProps) {
  const client = useQueryClient();
  const [form, setForm] = useState<SourceInput>({
    source_id: "",
    format: "syslog",
    path: allowedRoots[0] ?? "",
    glob: "**/*.log",
    timezone: "UTC",
    retention_days: 30,
    // Mixed streams are the common case (ADR-0012); a discovery suggestion overrides this.
    template_id: AUTO_PARSER,
    ...initial,
  });
  const [kind, setKind] = useState<"file" | "loki">("file");
  const [loki, setLoki] = useState<LokiSettings>({
    url: "",
    query: "",
    auth: "none",
    backfill_hours: 24,
  });
  const [lokiSecret, setLokiSecret] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const templates = useQuery({
    queryKey: ["templates"],
    queryFn: api.templates,
    staleTime: 60_000,
  });
  const set = <K extends keyof SourceInput>(key: K, value: SourceInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const add = useMutation({
    mutationFn: api.addSource,
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["source-list"] });
      await client.invalidateQueries({ queryKey: ["sources"] }); // Search filter list
      onDone();
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!ID_PATTERN.test(form.source_id)) {
      setLocalError(
        "Source ID: lowercase letters, digits, and underscores, starting with a letter or digit.",
      );
      return;
    }
    setLocalError(null);
    if (kind === "loki") {
      add.mutate({
        ...form,
        kind: "loki",
        path: "",
        glob: "*",
        loki: { ...loki, url: loki.url.trim(), query: loki.query.trim() },
        loki_secret: loki.auth !== "none" && lokiSecret ? lokiSecret : undefined,
      });
      return;
    }
    add.mutate(form);
  };

  const serverError = add.error instanceof ApiError ? add.error.message : null;

  return (
    <form
      onSubmit={submit}
      aria-label="Add source"
      className="rounded-card border border-border bg-surface p-4"
    >
      <h2 className="mb-3 text-base font-semibold">Add source</h2>
      <div className="grid gap-4 md:grid-cols-2">
        <Field
          label="Source ID"
          help="Used in queries, e.g. linux_auth or paloalto_traffic. Cannot be changed later."
          value={form.source_id}
          onChange={(e) => set("source_id", e.target.value.trim())}
          className="font-mono"
          required
        />
        <div className="flex flex-col gap-1">
          <label htmlFor="source-parser" className="text-sm font-semibold">
            Parser
          </label>
          <ParserSelect
            id="source-parser"
            templateId={form.template_id}
            format={form.format}
            templates={templates.data ?? []}
            formats={FORMATS}
            onChange={(templateId, format) =>
              setForm((f) => ({ ...f, template_id: templateId, format }))
            }
          />
          <p className="text-sm text-text-muted">
            {parserHelp(form.template_id, templates.data ?? [])}
          </p>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="source-kind" className="text-sm font-semibold">
            Reads from
          </label>
          <select
            id="source-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as "file" | "loki")}
            className="h-9 rounded border border-border-strong bg-inset px-2 text-sm text-text"
          >
            <option value="file">A file or folder on this server</option>
            <option value="loki">Grafana Loki</option>
          </select>
          <p className="text-sm text-text-muted">
            {kind === "loki"
              ? "Lines are copied from Loki every 30 seconds and parsed like a file."
              : "Files are read as they grow; rotated files are followed."}
          </p>
        </div>
        {kind === "loki" ? (
          <LokiFields
            value={loki}
            secret={lokiSecret}
            onChange={setLoki}
            onSecret={setLokiSecret}
          />
        ) : (
          <>
            <Field
              label="File or folder"
              help={
                allowedRoots.length
                  ? `Must be inside: ${allowedRoots.join(", ")}`
                  : "No folders are allowed yet. Set paths.allowed_roots on the server."
              }
              value={form.path}
              onChange={(e) => set("path", e.target.value)}
              className="font-mono"
              required
            />
            <Field
              label="File pattern"
              help="For folders. **/*.log matches every .log file in all subfolders."
              value={form.glob}
              onChange={(e) => set("glob", e.target.value)}
              className="font-mono"
            />
          </>
        )}
        <Field
          label="Time zone"
          help="For syslog lines without a zone, e.g. America/Los_Angeles."
          value={form.timezone}
          onChange={(e) => set("timezone", e.target.value)}
        />
        <Field
          label="Keep data for (days)"
          type="number"
          min={1}
          max={3650}
          value={form.retention_days}
          onChange={(e) => set("retention_days", Number(e.target.value))}
        />
      </div>
      <p className="mt-3 text-sm text-text-muted">
        New sources are local only: their data is never sent to a cloud AI provider. An
        administrator can allow cloud for a source later, from this list.
      </p>
      <div className="mt-3">
        <FormError message={localError ?? serverError} />
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          disabled={add.isPending}
          className="h-8 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {add.isPending ? "Adding" : "Add source"}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="h-8 rounded border border-border-strong px-4 text-sm text-text hover:bg-surface-head"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
