import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, type LibraryQuery } from "@/lib/api";
import { cn } from "@/lib/cn";

export interface LibraryPick extends LibraryQuery {
  pack: string;
  packName: string;
}

interface LibraryPanelProps {
  onLoad: (q: LibraryPick) => void;
  onClose: () => void;
  canSave: boolean;
}

/** Lines of `a` and `b` marked kept, removed, or added (a small LCS diff for SQL). */
export function lineDiff(a: string, b: string): { kind: " " | "-" | "+"; text: string }[] {
  const x = a.split("\n");
  const y = b.split("\n");
  const n = x.length;
  const m = y.length;
  const t: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      t[i]![j] = x[i] === y[j] ? t[i + 1]![j + 1]! + 1 : Math.max(t[i + 1]![j]!, t[i]![j + 1]!);
  const out: { kind: " " | "-" | "+"; text: string }[] = [];
  let i = 0;
  let j = 0;
  while (i < n || j < m) {
    if (i < n && j < m && x[i] === y[j]) {
      out.push({ kind: " ", text: x[i]! });
      i++;
      j++;
    } else if (j < m && (i >= n || t[i]![j + 1]! >= t[i + 1]![j]!)) {
      out.push({ kind: "+", text: y[j]! });
      j++;
    } else {
      out.push({ kind: "-", text: x[i]! });
      i++;
    }
  }
  return out;
}

/** Query library (ADR-0033): shipped, tested questions for the sources the viewer has,
 * grouped. Clicking one loads its SQL into the editor, unsaved; nothing runs from here. */
export function LibraryPanel({ onLoad, onClose, canSave }: LibraryPanelProps) {
  const client = useQueryClient();
  const lib = useQuery({ queryKey: ["library"], queryFn: api.library });
  const [filter, setFilter] = useState("");
  const [diffFor, setDiffFor] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);
  const refresh = () => {
    void client.invalidateQueries({ queryKey: ["library"] });
    void client.invalidateQueries({ queryKey: ["searches"] });
  };
  const save = useMutation({
    mutationFn: (v: { pack: string; id: string }) => api.libraryCopy(v.pack, v.id),
    onSuccess: (s) => {
      setNote(`Saved as ${s.name} (${s.id}), private to you.`);
      refresh();
    },
  });
  const replace = useMutation({
    mutationFn: (v: { pack: string; id: string }) => api.libraryReplace(v.pack, v.id),
    onSuccess: (s) => {
      setNote(`Your copy ${s.id} now has this version's SQL.`);
      setDiffFor(null);
      refresh();
    },
  });
  const needle = filter.trim().toLowerCase();
  const match = (q: LibraryQuery) =>
    !needle ||
    q.name.toLowerCase().includes(needle) ||
    q.id.includes(needle) ||
    q.group.toLowerCase().includes(needle) ||
    q.tags.some((t) => t.includes(needle));
  const error = save.error ?? replace.error;

  return (
    <section
      aria-label="Query library"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
      className="rounded-card border border-border bg-surface"
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
        <label htmlFor="library-filter" className="text-sm font-semibold">
          Query library
        </label>
        <input
          id="library-filter"
          ref={input}
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by name, group, or tag"
          className="h-8 min-w-0 flex-1 rounded border border-border bg-inset px-2 text-sm"
        />
        <button
          type="button"
          onClick={onClose}
          className="h-8 rounded px-2 text-sm text-text-secondary hover:text-text"
        >
          Close
        </button>
      </div>
      {note ? (
        <p role="status" className="border-b border-border px-3 py-1.5 text-sm text-text-secondary">
          {note}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="border-b border-border px-3 py-1.5 text-sm text-warn">
          {(error as Error).message}
        </p>
      ) : null}
      {lib.isLoading ? (
        <div aria-busy="true" className="h-24 animate-pulse" />
      ) : lib.isError ? (
        <p role="alert" className="px-3 py-3 text-sm text-warn">
          The library did not load: {(lib.error as Error).message}
        </p>
      ) : lib.data && lib.data.packs.length === 0 ? (
        <p className="px-3 py-3 text-sm text-text-secondary">
          No library query fits your sources yet. Queries appear once a source you can read sends
          events from one of their templates.
        </p>
      ) : (
        <div className="max-h-[28rem] overflow-y-auto">
          {(lib.data?.packs ?? []).map((p) => {
            const groups = new Map<string, LibraryQuery[]>();
            for (const q of p.queries.filter(match)) {
              groups.set(q.group, [...(groups.get(q.group) ?? []), q]);
            }
            if (!groups.size) return null;
            return (
              <div key={p.id}>
                {[...groups.entries()].map(([g, qs]) => (
                  <div key={g}>
                    <h3 className="sticky top-0 border-b border-border bg-surface-head px-3 py-1 text-sm font-semibold">
                      {g}
                    </h3>
                    <ul className="flex flex-col">
                      {qs.map((q) => {
                        const key = `${p.id}/${q.id}`;
                        return (
                          <li key={key} className="border-b border-border px-3 py-2 last:border-0">
                            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                              <button
                                type="button"
                                onClick={() => onLoad({ ...q, pack: p.id, packName: p.name })}
                                className="text-left font-semibold text-accent-text hover:underline"
                              >
                                {q.name}
                              </button>
                              {q.my_copy?.updated ? (
                                <button
                                  type="button"
                                  aria-expanded={diffFor === key}
                                  onClick={() => setDiffFor(diffFor === key ? null : key)}
                                  className="rounded-badge bg-accent-subtle px-1.5 py-px text-xs text-accent-text"
                                >
                                  Updated in this version
                                </button>
                              ) : q.my_copy ? (
                                <span className="text-xs text-text-muted">
                                  Saved as {q.my_copy.search_id}
                                </span>
                              ) : null}
                              {canSave && !q.my_copy ? (
                                <button
                                  type="button"
                                  onClick={() => save.mutate({ pack: p.id, id: q.id })}
                                  disabled={save.isPending}
                                  className="ml-auto text-sm text-text-secondary hover:text-text"
                                  aria-label={`Save ${q.name} as my own`}
                                >
                                  Save as my own
                                </button>
                              ) : null}
                            </div>
                            <p className="text-sm">{q.why}</p>
                            <p className="text-sm text-text-muted">Normal: {q.normal}</p>
                            {diffFor === key && q.my_copy ? (
                              <div className="mt-2 flex flex-col gap-2">
                                <pre
                                  aria-label={`Changes to ${q.name}`}
                                  className="max-h-60 overflow-auto rounded border border-border bg-inset px-2 py-1.5 font-mono text-xs"
                                >
                                  {lineDiff(q.my_copy.sql, q.pack_sql).map((l, i) => (
                                    <div
                                      key={i}
                                      className={cn(
                                        l.kind === "+" && "text-accent-text",
                                        l.kind === "-" && "text-text-muted line-through",
                                      )}
                                    >
                                      {l.kind} {l.text}
                                    </div>
                                  ))}
                                </pre>
                                {canSave ? (
                                  <button
                                    type="button"
                                    onClick={() => replace.mutate({ pack: p.id, id: q.id })}
                                    disabled={replace.isPending}
                                    className="h-8 self-start rounded border border-border px-3 text-sm hover:bg-surface-head"
                                  >
                                    Replace my copy
                                  </button>
                                ) : null}
                              </div>
                            ) : null}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}
      {lib.data?.hidden ? (
        <p className="border-t border-border px-3 py-1.5 text-xs text-text-muted">
          {lib.data.hidden} more {lib.data.hidden === 1 ? "query needs" : "queries need"} sources
          you do not have events from.
        </p>
      ) : null}
    </section>
  );
}
