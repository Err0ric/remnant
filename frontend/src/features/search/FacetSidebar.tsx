import { useQuery } from "@tanstack/react-query";
import { useState, type MouseEvent } from "react";
import { Truncate } from "@/components/Truncate";
import { ApiError, api, type FacetRequest } from "@/lib/api";
import { columnLabel, SEVERITY } from "@/lib/search";
import { filterTerm } from "@/lib/simpleSearch";

interface FacetSidebarProps {
  /** The search behind the results on screen; null before the first run. */
  request: FacetRequest | null;
  /** Adds a term to the Simple search and runs it; null in SQL mode. */
  onTerm: ((term: string) => void) | null;
  /** SQL and Ask mode: adds the filter to the SQL on screen and runs it. */
  onRefine?: ((field: string, value: string | null, exclude: boolean) => void) | null;
  /** The results card's count for the same run ("1,133", or "10,000+" at the limit). */
  total?: { count: number; more: boolean } | null;
}

/** The note over counts taken from the newest days only, with the numbers named. */
export function sampledNote(
  days: number,
  items: number,
  skipped: boolean,
  total: { count: number; more: boolean } | null,
): string {
  if (days === 0)
    return "None of the matches fell in the days that could be counted in time. The results are not affected.";
  const span = `the newest ${days === 1 ? "day" : `${days} days`}${skipped ? " with matches" : ""}`;
  const counted = `${items.toLocaleString()} ${items === 1 ? "item" : "items"}`;
  // Never a part larger than its whole: past the results' own count (the first page stops
  // at its limit), say how many were counted and where the results stop.
  const of = !total
    ? ` (${counted})`
    : items > total.count
      ? ` (${counted} counted${total.more ? `; the results stop at ${total.count.toLocaleString()}` : ""})`
      : ` (${items.toLocaleString()} of ${total.count.toLocaleString()}${total.more ? "+" : ""} items)`;
  return `Counts from ${span} only${of}: the whole range took too long to count. The results are not affected.`;
}

// Simple-search names for the facet columns (the short aliases where one exists).
const SEARCH_NAME: Record<string, string> = {
  source_id: "source",
  device_hostname: "host",
  actor_user_name: "user",
  src_endpoint_ip: "src_ip",
  dst_endpoint_ip: "dst_ip",
  severity_id: "severity",
};

const STATUS: Record<string, string> = { "0": "Unknown", "1": "Success", "2": "Failure" };
const CLASSES: Record<string, string> = {
  "1001": "File activity",
  "1007": "Process activity",
  "3001": "Account change",
  "3002": "Authentication",
  "3003": "Authorize session",
  "4001": "Network activity",
  "4002": "HTTP activity",
  "4003": "DNS activity",
  "6003": "API activity",
};

function label(field: string, value: string | null): string {
  if (value === null || value === "") return "(no value)";
  if (field === "severity_id") return SEVERITY[Number(value)]?.label ?? value;
  if (field === "status_id") return STATUS[value] ?? value;
  if (field === "class_uid") return CLASSES[value] ? `${CLASSES[value]} (${value})` : value;
  return value;
}

const OPEN_KEY = "search-facets-open";
function storedOpen(): boolean {
  // Open beside the results on wide screens; on phones it would push them down a page.
  const wide =
    typeof window.matchMedia !== "function" || window.matchMedia("(min-width: 1024px)").matches;
  try {
    const v = window.localStorage.getItem(OPEN_KEY);
    return v === null ? wide : v === "1";
  } catch {
    return wide;
  }
}

/** Top values of a few fields for the whole result, from the server (ADR-0016 row 2). */
export function FacetSidebar({
  request,
  onTerm,
  onRefine = null,
  total = null,
}: FacetSidebarProps) {
  const [open, setOpenState] = useState(storedOpen);
  const setOpen = (v: boolean) => {
    setOpenState(v);
    try {
      window.localStorage.setItem(OPEN_KEY, v ? "1" : "0");
    } catch {
      // storage blocked: the choice lasts for this visit
    }
  };
  const facets = useQuery({
    queryKey: ["facets", request],
    queryFn: () => api.facets(request as FacetRequest),
    enabled: open && request !== null,
    staleTime: 30_000,
    // Keep the last counts on screen while the next ones load (no flicker, no lost clicks).
    placeholderData: (previous) => previous,
  });

  const clickable = onTerm !== null || onRefine !== null;
  // Counted over the newest days only (null: the whole range was counted).
  const sampled = facets.data != null && facets.data.sampled_days != null;
  const pick = (field: string, value: string | null, exclude: boolean) => {
    if (!onTerm) {
      onRefine?.(field, value, exclude);
      return;
    }
    const name = SEARCH_NAME[field] ?? field;
    if (value === null || value === "") onTerm(`${exclude ? "" : "-"}${name}:*`);
    else onTerm(filterTerm(name, value, exclude));
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-expanded={false}
        className="h-8 shrink-0 self-start rounded border border-border px-2.5 text-sm text-text-secondary hover:bg-surface-head"
      >
        Show fields
      </button>
    );
  }
  return (
    <aside
      aria-label="Fields"
      className="w-full shrink-0 self-start rounded border border-border bg-surface lg:w-60"
    >
      <div className="flex items-center gap-2 border-b border-border bg-surface-head px-3 py-2">
        <h2 className="text-sm font-semibold">Fields</h2>
        <span className="truncate text-xs font-normal text-text-muted">
          {clickable ? "click to filter" : "counts only"}
        </span>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-expanded={true}
          className="ml-auto text-sm text-text-secondary hover:text-text"
        >
          Hide
        </button>
      </div>
      {facets.isPending && request && !facets.data ? (
        <p className="px-3 py-2 text-sm text-text-muted">Counting…</p>
      ) : null}
      {facets.isError ? (
        <div role="alert" className="flex items-start gap-2 px-3 py-2 text-sm">
          <p className="min-w-0 flex-1 text-danger">
            {facets.error instanceof ApiError && facets.error.status === 408
              ? "Counting fields took too long for this range. The results are not affected."
              : facets.error instanceof Error
                ? facets.error.message
                : "Could not count fields"}
          </p>
          <button
            type="button"
            onClick={() => void facets.refetch()}
            className="shrink-0 text-text-secondary underline hover:text-text"
          >
            Retry
          </button>
        </div>
      ) : null}
      {sampled ? (
        <p className="border-b border-border px-3 py-2 text-xs text-text-muted" role="note">
          {sampledNote(
            facets.data?.sampled_days ?? 0,
            facets.data?.sampled_items ?? 0,
            Boolean(facets.data?.sampled_skipped),
            total,
          )}
        </p>
      ) : null}
      {facets.data && facets.data.facets.length === 0 && !sampled ? (
        <p className="px-3 py-2 text-sm text-text-muted">
          No countable fields in this result. Facets cover source, host, user, addresses, severity,
          status, class, and parse status.
        </p>
      ) : null}
      <div className="flex flex-col">
        {(facets.data?.facets ?? [])
          // A field with no value anywhere in the result says nothing; leave it out.
          .filter((f) => f.values.some((v) => v.value !== null && v.value !== ""))
          .map((f) => {
            const top = Math.max(...f.values.map((v) => v.count), 1);
            return (
              <section
                key={f.field}
                aria-label={columnLabel(f.field)}
                className="border-b border-border px-3 py-2 last:border-0"
              >
                <h3 className="mb-1 text-xs text-text-muted">{columnLabel(f.field)}</h3>
                <ul className="flex flex-col gap-px">
                  {f.values.map((v) => {
                    const text = label(f.field, v.value);
                    return (
                      <li key={v.value ?? "\u0000"} className="group flex items-center gap-1">
                        <button
                          type="button"
                          disabled={!clickable}
                          onClick={(e: MouseEvent) => pick(f.field, v.value, e.altKey)}
                          title={clickable ? `Filter to ${text}` : text}
                          // The value whole, however it is cut (D257), then its count.
                          aria-label={`${text} ${v.count.toLocaleString()}`}
                          className="relative flex min-w-0 flex-1 items-center gap-2 rounded px-1.5 py-0.5 text-left text-sm enabled:hover:bg-surface-head disabled:cursor-default"
                        >
                          <span
                            aria-hidden="true"
                            className="absolute inset-y-0 left-0 rounded bg-accent-subtle"
                            style={{ width: `${Math.max(4, (v.count / top) * 100)}%` }}
                          />
                          {v.value && text === v.value ? (
                            // A long source id or name is cut in the middle (D257); the
                            // button's title holds it whole. Labels ("Authentication") are not.
                            <span className="relative min-w-0 flex-1 font-mono">
                              <Truncate
                                value={text}
                                kind={text.includes("@") ? "email" : "name"}
                                inLink
                              />
                            </span>
                          ) : (
                            <span
                              className={`relative min-w-0 flex-1 truncate ${v.value ? "font-mono" : "italic text-text-secondary"}`}
                            >
                              {text}
                            </span>
                          )}
                          <span className="relative shrink-0 font-mono tabular-nums text-text-secondary">
                            {v.count.toLocaleString()}
                          </span>
                        </button>
                        {clickable ? (
                          <button
                            type="button"
                            onClick={() => pick(f.field, v.value, true)}
                            aria-label={`Exclude ${text}`}
                            title="Exclude"
                            className="h-5 w-5 shrink-0 rounded text-sm text-text-muted opacity-0 hover:bg-surface-head hover:text-text focus:opacity-100 group-hover:opacity-100"
                          >
                            −
                          </button>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
      </div>
    </aside>
  );
}
