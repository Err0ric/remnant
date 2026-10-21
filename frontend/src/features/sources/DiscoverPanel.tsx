import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Field } from "@/features/auth/Field";
import { FormError } from "@/features/auth/FormError";
import { seedDraft } from "@/features/templates/draftSeed";
import { ApiError, api, type DiscoveryCandidate, type SourceInput } from "@/lib/api";
import { navigate } from "@/lib/route";

interface DiscoverPanelProps {
  allowedRoots: string[];
  /** Source ids already in use, so suggestions do not collide with them. */
  existingIds: string[];
  /** Opens the add form with these values; nothing is created until the admin submits it. */
  onUse: (values: Partial<SourceInput>) => void;
  onClose: () => void;
}

const SKIP_REASONS: Record<string, string> = {
  compressed: "compressed",
  outside_allowed_roots: "outside the allowed folders",
  too_deep: "folders too deep",
  rotated: "rotated copies",
  not_a_file: "not regular files",
};

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/** A template id from the file name: lowercase, starting with a letter. */
function draftId(c: DiscoveryCandidate): string {
  const name = (c.glob.split("/").pop() ?? "")
    .toLowerCase()
    .replace(/\.(log|txt|evtx|json|jsonl|csv)\*?$/, "")
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
  const id = /^[a-z]/.test(name) ? name : `logs_${name}`;
  return id.slice(0, 64).replace(/_+$/, "") || "new_template";
}

function baseId(c: DiscoveryCandidate): string {
  const best = c.matches[0];
  const base = best?.passes ? best.template_id : (c.glob.split("/").pop() ?? "source");
  const id = base
    .toLowerCase()
    .replace(/\.(log|txt|evtx|json)\*?$/, "")
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 64);
  return /^[a-z0-9]/.test(id) ? id : `src_${id}`.slice(0, 64);
}

/** One id per candidate, unique among the candidates and the existing sources. */
function suggestedIds(candidates: DiscoveryCandidate[], existing: string[]): Map<string, string> {
  const taken = new Set(existing);
  const out = new Map<string, string>();
  for (const c of candidates) {
    const base = baseId(c);
    let id = base;
    for (let n = 2; taken.has(id); n += 1) id = `${base.slice(0, 60)}_${n}`;
    taken.add(id);
    out.set(c.glob, id);
  }
  return out;
}

function valuesFor(c: DiscoveryCandidate, sourceId: string): Partial<SourceInput> {
  const best = c.matches[0];
  const useTemplate = best?.passes && best.parse_rate >= 0.8;
  return {
    source_id: sourceId,
    path: c.path,
    glob: c.glob,
    template_id: useTemplate ? best.template_id : null,
    // Generic CSV needs a header row, which a sniff cannot confirm; syslog keeps each line.
    format: c.sniff?.format === "json" ? "json" : "syslog",
  };
}

export function DiscoverPanel({ allowedRoots, existingIds, onUse, onClose }: DiscoverPanelProps) {
  const [path, setPath] = useState(allowedRoots[0] ?? "");
  const scan = useMutation({ mutationFn: api.discoverSources });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    scan.mutate(path);
  };
  const report = scan.data;
  const skipped = Object.entries(report?.skipped ?? {}).filter(([, n]) => n > 0);
  const ids = suggestedIds(report?.candidates ?? [], existingIds);

  return (
    <section
      aria-label="Discover sources"
      className="rounded-card border border-border bg-surface p-4"
    >
      <h2 className="mb-1 text-base font-semibold">Discover sources</h2>
      <p className="mb-3 text-sm text-text-muted">
        Reads a sample of each file and suggests a parser. Nothing is added or shared until you add
        a source yourself.
      </p>
      <form onSubmit={submit} className="flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1">
          <Field
            label="Folder"
            help={
              allowedRoots.length
                ? `Must be inside: ${allowedRoots.join(", ")}`
                : "No folders are allowed yet. Set paths.allowed_roots on the server."
            }
            value={path}
            onChange={(e) => setPath(e.target.value)}
            className="font-mono"
            required
          />
        </div>
        <button
          type="submit"
          disabled={scan.isPending}
          className="mb-6 h-8 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {scan.isPending ? "Scanning" : "Scan folder"}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="mb-6 h-8 rounded border border-border-strong px-4 text-sm text-text hover:bg-surface-head"
        >
          Close
        </button>
      </form>
      <FormError message={scan.error instanceof ApiError ? scan.error.message : null} />

      {report ? (
        <div className="mt-2">
          <p className="mb-2 text-sm text-text-secondary">
            {report.candidates.length} {report.candidates.length === 1 ? "candidate" : "candidates"}{" "}
            in <span className="font-mono">{report.root}</span>
            {skipped.length
              ? ` · skipped: ${skipped
                  .map(([reason, n]) => `${n} ${SKIP_REASONS[reason] ?? reason}`)
                  .join(", ")}`
              : ""}
            {report.truncated ? " · stopped early: the folder is large, scan a subfolder" : ""}
          </p>
          {report.candidates.length === 0 ? (
            <p className="text-sm text-text-secondary">No log files found in this folder.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-text-secondary">
                    <th className="px-2 py-2 font-semibold">Files</th>
                    <th className="px-2 py-2 font-semibold">Hosts</th>
                    <th className="px-2 py-2 font-semibold">Looks like</th>
                    <th className="px-2 py-2 font-semibold">Suggested parser</th>
                    <th className="px-2 py-2" aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {report.candidates.map((c) => {
                    const best = c.matches[0];
                    return (
                      <tr key={c.glob} className="border-b border-border align-top last:border-0">
                        <td className="px-2 py-2">
                          <div className="font-mono break-all">{c.glob}</div>
                          <div className="text-text-muted">
                            {c.files} {c.files === 1 ? "file" : "files"}
                          </div>
                          {c.extra_matches > 0 ? (
                            <div className="mt-1 text-text-secondary">
                              <span className="font-semibold text-text">Check the pattern:</span> it
                              also matches {c.extra_matches} other{" "}
                              {c.extra_matches === 1 ? "file" : "files"}; narrow it before adding.
                            </div>
                          ) : null}
                          {c.preview[0] ? (
                            <div
                              className="mt-1 max-w-md truncate font-mono text-text-muted"
                              title={c.preview.join("\n")}
                            >
                              {c.preview[0]}
                            </div>
                          ) : null}
                        </td>
                        <td className="px-2 py-2 font-mono">
                          {c.hosts.length === 0
                            ? "·"
                            : `${c.hosts.slice(0, 3).join(", ")}${
                                c.hosts.length > 3 ? ` +${c.hosts.length - 3}` : ""
                              }`}
                        </td>
                        <td className="px-2 py-2">
                          {c.kind === "evtx"
                            ? "Windows .evtx"
                            : c.kind === "binary"
                              ? "Binary, not a text log"
                              : c.sniff
                                ? `${c.sniff.format}${
                                    (c.sniff.envelope["none"] ?? 0) < c.sniff.lines
                                      ? " over syslog"
                                      : ""
                                  }`
                                : "·"}
                        </td>
                        <td className="px-2 py-2">
                          {best?.passes ? (
                            <>
                              <div>{best.name}</div>
                              <div className="text-text-muted tabular-nums">
                                matches {percent(best.confidence)} · parses{" "}
                                {percent(best.parse_rate)}
                              </div>
                            </>
                          ) : (
                            <span className="text-text-secondary">
                              No template fits; a generic parser keeps every line
                            </span>
                          )}
                        </td>
                        <td className="px-2 py-2 text-right">
                          {c.kind === "text" && !best?.passes ? (
                            <button
                              type="button"
                              onClick={() => {
                                seedDraft({ templateId: draftId(c), path: c.path, glob: c.glob });
                                navigate("templates");
                              }}
                              aria-label={`Write a parser for ${c.glob}`}
                              className="mb-1 whitespace-nowrap rounded border border-border-strong px-2 py-0.5 text-text hover:bg-surface-head"
                            >
                              Write a parser
                            </button>
                          ) : null}{" "}
                          {c.kind === "text" || (c.kind === "evtx" && best?.passes) ? (
                            <button
                              type="button"
                              onClick={() => onUse(valuesFor(c, ids.get(c.glob) ?? ""))}
                              aria-label={`Add source for ${c.glob}`}
                              className="whitespace-nowrap rounded border border-border-strong px-2 py-0.5 text-text hover:bg-surface-head"
                            >
                              Add as source
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
