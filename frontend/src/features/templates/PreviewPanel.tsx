import type { DraftPreview } from "@/lib/api";

interface PreviewPanelProps {
  preview: DraftPreview;
}

function percent(n: number, of: number): string {
  return of ? `${Math.round((n / of) * 100)}%` : "·";
}

/** What the template does with the sample: problems, tests, then parsed rows. */
export function PreviewPanel({ preview }: PreviewPanelProps) {
  return (
    <section aria-label="Preview" className="flex flex-col gap-3">
      {preview.errors.length ? (
        <div role="alert" className="rounded-card border border-danger bg-surface p-3 text-sm">
          <p className="font-semibold text-danger">
            {preview.valid ? "Not ready to approve" : "Not a valid template"}
          </p>
          <ul className="mt-1 list-disc pl-5">
            {preview.errors.map((e) => (
              <li key={e} className="break-words">
                {e}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-sm font-semibold text-ok">Ready to approve</p>
      )}

      {preview.tests.length ? (
        <div>
          <h3 className="mb-1 text-sm font-semibold">Inline tests</h3>
          <ul className="text-sm">
            {preview.tests.map((t) => (
              <li key={t.name}>
                <span className={t.passed ? "text-ok" : "text-danger"}>
                  {t.passed ? "Passed" : "Failed"}
                </span>{" "}
                {t.name}
                {t.problems.length ? (
                  <span className="text-text-secondary">: {t.problems.join("; ")}</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {preview.valid ? (
        <div>
          <h3 className="mb-1 text-sm font-semibold">Sample</h3>
          {preview.lines === 0 ? (
            <p className="text-sm text-text-secondary">
              No sample lines. Attach a file or paste lines to see how they parse.
            </p>
          ) : (
            <>
              <p className="mb-2 text-sm text-text-secondary tabular-nums">
                {preview.lines} lines · parsed {percent(preview.ok, preview.lines)} · partly{" "}
                {percent(preview.partial, preview.lines)} · not parsed{" "}
                {percent(preview.failed, preview.lines)}
                {preview.rows.length < preview.lines ? ` · first ${preview.rows.length} shown` : ""}
              </p>
              {/* Its own scroll area: 50 rows of fields would otherwise make the page
                  thousands of pixels tall beside a short editor. */}
              <div className="max-h-[70vh] overflow-auto rounded-card border border-border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="sticky top-0 border-b border-border bg-surface-head text-left text-text-secondary">
                      <th className="px-2 py-1.5 font-semibold">Line</th>
                      <th className="px-2 py-1.5 font-semibold">Status</th>
                      <th className="px-2 py-1.5 font-semibold">Class</th>
                      <th className="px-2 py-1.5 font-semibold">Fields</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((r) => (
                      <tr key={r.line} className="border-b border-border align-top last:border-0">
                        <td className="px-2 py-1.5 font-mono tabular-nums">{r.line}</td>
                        <td className="px-2 py-1.5">
                          <div>{r.parse_status}</div>
                          {r.parse_errors ? (
                            <div className="font-mono text-text-muted">{r.parse_errors}</div>
                          ) : null}
                        </td>
                        <td className="px-2 py-1.5 font-mono">{r.class_uid ?? "·"}</td>
                        <td className="px-2 py-1.5 font-mono">
                          <div className="break-all text-text-muted">{r.raw}</div>
                          <dl className="mt-1 grid grid-cols-[max-content_1fr] gap-x-3">
                            {Object.entries(r.fields).map(([k, v]) => (
                              <div key={k} className="contents">
                                <dt className="text-text-secondary">{k}</dt>
                                <dd className="break-all">{v === null ? "·" : String(v)}</dd>
                              </div>
                            ))}
                          </dl>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      ) : null}
    </section>
  );
}
