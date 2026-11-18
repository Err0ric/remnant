import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { FilterBar } from "@/components/FilterBar";
import { InlineError } from "@/components/InlineError";
import { Skeleton } from "@/components/Skeleton";
import { PageHeader } from "@/components/shell/PageHeader";
import { currentDashboard } from "@/features/dashboard/choice";
import { ApiError, api, type LibraryPack, type LibraryQuery } from "@/lib/api";
import { cn } from "@/lib/cn";
import { fragmentValues, navigate, pathFor, setFragment, useSection } from "@/lib/route";
import { seedSearch } from "@/lib/searchSeed";
import { fitsInLogs, TOO_LONG_FOR_LOGS } from "@/lib/sqlLimit";
import { useViewer } from "@/lib/viewer";

interface LibraryPageProps {
  /** Admins and analysts: Save as my own, Add to dashboard, Replace my copy. */
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

const plural = (n: number) => `${n} ${n === 1 ? "query" : "queries"}`;

/** The sources a query reads, by their plain names; any one of several is enough. */
function sourcesLine(q: LibraryQuery): string {
  if (!q.sources.length) return "Sources: any";
  return q.sources.length === 1
    ? `Sources: ${q.sources[0]}`
    : `Sources, any one of: ${q.sources.join(", ")}`;
}

/** Why a query in "Needs sources you don't have" cannot run: "Needs a Linux sudo source". */
function needsLine(q: LibraryQuery): string {
  return `Needs a ${q.sources.join(" or ")} source`;
}

const NEEDS = "None of your sources sent events of these kinds in the last 30 days.";

const ACTION = "h-7 whitespace-nowrap px-1 text-accent-text hover:underline disabled:opacity-50";

/** Logs > Library (ADR-0033, owner 2026-11-17): the shipped, tested queries, by pack, with
 * the ones whose sources the viewer has no events from in their own group at the end.
 * Run opens a query in the Logs SQL editor, unsaved, with its why and Normal line over
 * the last 24 hours; it does not run until the person presses Logs' own Run (row 4). */
export function LibraryPage({ canSave }: LibraryPageProps) {
  const client = useQueryClient();
  const { isAdmin } = useViewer();
  const [detailsFor, setDetailsFor] = useState<string | null>(null);
  const lib = useQuery({ queryKey: ["library"], queryFn: api.library });
  const frag = fragmentValues(useSection());
  const text = frag.get("q") ?? "";
  const packId = frag.get("pack") ?? "all";
  const setFilters = (q: string, pack: string) => {
    const next = new URLSearchParams();
    if (pack !== "all") next.set("pack", pack);
    if (q) next.set("q", q);
    setFragment(next.toString(), true);
  };
  const [diffFor, setDiffFor] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
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
  // Add a pack (ADR-0033 row 5) with one query ticked: the viewer's copy, a private
  // schedule at the query's suggested interval, and a panel on their current dashboard.
  // Queries added from this page: their row says "On your dashboard" instead of the
  // button. The server makes nothing for one already there, so a second add is harmless.
  const [onBoard, setOnBoard] = useState<Set<string>>(new Set());
  const add = useMutation({
    mutationFn: async (v: { pack: string; q: LibraryQuery }) => {
      const out = await api.addPack(v.pack, [v.q.id], currentDashboard() ?? undefined);
      // Run a new one once so the panel fills now; a failure shows on the panel.
      const made = out.added.filter((a) => !a.existing);
      await Promise.allSettled(made.map((a) => api.runSchedule(a.schedule_id)));
      return { ...v, existing: made.length === 0 };
    },
    onSuccess: ({ pack, q, existing }) => {
      setOnBoard((s) => new Set(s).add(`${pack}/${q.id}`));
      setNote(
        existing
          ? `${q.name} is already on your dashboard.`
          : `Added ${q.name} to your dashboard, as a private saved search and schedule.`,
      );
      refresh();
      void client.invalidateQueries({ queryKey: ["dashboards"] });
      void client.invalidateQueries({ queryKey: ["schedules"] });
    },
  });
  const error = save.error ?? replace.error ?? add.error;

  const needle = text.trim().toLowerCase();
  const match = (q: LibraryQuery) =>
    !needle ||
    [q.name, q.description, q.why, q.group].some((s) => s.toLowerCase().includes(needle));
  const pick = (packs: LibraryPack[]) =>
    packs
      .filter((p) => packId === "all" || p.id === packId)
      .map((p) => ({ ...p, queries: p.queries.filter(match) }))
      .filter((p) => p.queries.length > 0);
  const all = [...(lib.data?.packs ?? []), ...(lib.data?.needs ?? [])];
  const total = all.reduce((n, p) => n + p.queries.length, 0);
  const packs = pick(lib.data?.packs ?? []);
  const needs = pick(lib.data?.needs ?? []).flatMap((p) => p.queries.map((q) => ({ p, q })));
  const shown = packs.reduce((n, p) => n + p.queries.length, 0) + needs.length;
  const isDefault = !text && packId === "all";
  const packOptions = [
    { id: "all", label: "All" },
    ...[...new Map(all.map((p) => [p.id, p.name])).entries()].map(([id, label]) => ({ id, label })),
  ];

  const open = (p: LibraryPack, q: LibraryQuery) => {
    seedSearch({
      sql: q.sql,
      range: "24h",
      library: {
        name: q.name,
        packName: p.name,
        why: q.why,
        normal: q.normal,
        packSql: q.pack_sql,
        empty: q.empty,
      },
    });
    navigate("logs");
  };

  const row = (p: LibraryPack, q: LibraryQuery, missing: boolean) => {
    const key = `${p.id}/${q.id}`;
    const fits = fitsInLogs(q.sql);
    // Why Run is off: the source it needs (on hover and to screen readers; the Sources line
    // shows it), or a query too long for Logs (said on the row).
    const reasonId = `why-not-${p.id}-${q.id}`;
    const reason = missing ? needsLine(q) : fits ? null : `${TOO_LONG_FOR_LOGS} Ask AI answers it.`;
    const details = detailsFor === key;
    return (
      <li
        key={key}
        className="flex flex-wrap items-start gap-x-4 gap-y-1 border-b border-border px-3 py-2 text-sm last:border-0"
      >
        <div className="flex min-w-0 flex-[1_1_480px] flex-col gap-0.5">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="font-semibold">{q.name}</span>
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
              <span className="text-xs text-text-muted">Saved as {q.my_copy.search_id}</span>
            ) : null}
          </div>
          {/* The plain line Logs shows above the editor: one description per query. A
              query that needs a source shows only its Sources line, to keep that list short. */}
          {missing ? null : <p>{q.why}</p>}
          {missing ? null : <p className="text-text-muted">Normal: {q.normal}</p>}
          {/* Details sits at the end of the Sources line, so it adds no line of its own. */}
          <div className="flex flex-wrap items-center gap-x-3 text-text-secondary">
            <span>{sourcesLine(q)}</span>
            {!missing && q.description ? (
              <button
                type="button"
                aria-expanded={details}
                aria-label={`Details of ${q.name}`}
                onClick={() => setDetailsFor(details ? null : key)}
                className="flex items-center gap-1 hover:text-text"
              >
                <ChevronRight size={14} aria-hidden className={cn(details && "rotate-90")} />
                Details
              </button>
            ) : null}
          </div>
          {details ? <p className="text-text-secondary">{q.description}</p> : null}
          {reason ? (
            <p id={reasonId} className={missing ? "sr-only" : "text-text-muted"}>
              {reason}
            </p>
          ) : null}
          {diffFor === key && q.my_copy ? (
            <div className="mt-1 flex flex-col gap-2">
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
                  className="h-7 self-start rounded border border-border-strong px-2.5 hover:bg-surface-head"
                >
                  Replace my copy
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {reason ? (
            <button
              type="button"
              aria-disabled="true"
              aria-label={`Run ${q.name} in Logs`}
              aria-describedby={reasonId}
              title={reason}
              className="h-7 cursor-default whitespace-nowrap rounded border border-border px-2.5 text-text-muted"
            >
              Run
            </button>
          ) : (
            <button
              type="button"
              aria-label={`Run ${q.name} in Logs`}
              onClick={() => open(p, q)}
              className="h-7 whitespace-nowrap rounded border border-border-strong px-2.5 text-text hover:bg-surface-head"
            >
              Run
            </button>
          )}
          {canSave && !reason && !q.my_copy ? (
            <button
              type="button"
              aria-label={`Save ${q.name} as my own`}
              onClick={() => save.mutate({ pack: p.id, id: q.id })}
              disabled={save.isPending}
              className={ACTION}
            >
              Save as my own
            </button>
          ) : null}
          {canSave && !reason && onBoard.has(key) ? (
            <a
              href={pathFor("dashboard")}
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                e.preventDefault();
                navigate("dashboard");
              }}
              className="h-7 whitespace-nowrap px-1 leading-7 text-accent-text hover:underline"
            >
              On your dashboard
            </a>
          ) : canSave && !reason ? (
            <button
              type="button"
              aria-label={`Add ${q.name} to the dashboard`}
              onClick={() => add.mutate({ pack: p.id, q })}
              disabled={add.isPending}
              className={ACTION}
            >
              Add to dashboard
            </button>
          ) : null}
        </div>
      </li>
    );
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader title="Library" />
      <div className="flex flex-col gap-3 px-5 py-3">
        <FilterBar
          label="Filter the library"
          facets={[
            {
              name: "Pack",
              value: packId,
              options: packOptions,
              onChange: (id) => setFilters(text, id),
            },
          ]}
          text={{
            label: "Filter by name or description",
            value: text,
            onChange: (v) => setFilters(v, packId),
          }}
          count={lib.data ? (isDefault ? plural(total) : `${shown} of ${plural(total)}`) : null}
          onReset={() => setFilters("", "all")}
          isDefault={isDefault}
        />
        {note ? (
          <p role="status" className="text-sm text-text-secondary">
            {note}
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error instanceof ApiError ? error.message : "That did not work"}
          </p>
        ) : null}
        {lib.isPending ? (
          <Skeleton label="the library" rows={6} tall className="rounded-card" />
        ) : lib.isError ? (
          <InlineError
            what="The library"
            error={lib.error}
            onRetry={() => void lib.refetch()}
            retrying={lib.isFetching}
          />
        ) : shown === 0 ? (
          <section className="rounded-card border border-border bg-surface">
            {total === 0 ? (
              <EmptyState kind="not-set-up" title="No query packs are installed." />
            ) : (
              <EmptyState
                kind="filtered"
                title="No queries match these filters."
                action={{ label: "Reset filters", onClick: () => setFilters("", "all") }}
              />
            )}
          </section>
        ) : (
          <>
            {packs.map((p) => (
              <Card key={p.id} level="panel" title={p.name} note={plural(p.queries.length)}>
                <ul className="flex flex-col">{p.queries.map((q) => row(p, q, false))}</ul>
              </Card>
            ))}
            {needs.length ? (
              <Card level="panel" title="Needs sources you don't have" note={plural(needs.length)}>
                <p className="border-b border-border px-3 py-2 text-sm text-text-secondary">
                  {NEEDS}{" "}
                  {isAdmin ? (
                    <a
                      href={pathFor("sources")}
                      onClick={(e) => {
                        if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                        e.preventDefault();
                        navigate("sources");
                      }}
                      className="text-accent-text hover:underline"
                    >
                      Add a source
                    </a>
                  ) : (
                    "Ask an admin to add or share a source."
                  )}
                </p>
                <ul className="flex flex-col">{needs.map(({ p, q }) => row(p, q, true))}</ul>
              </Card>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
