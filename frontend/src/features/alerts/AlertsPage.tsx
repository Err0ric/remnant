import { SeverityMark } from "@/components/SeverityMark";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, type AlertItem, type CloseReason } from "@/lib/api";
import { InlineError } from "@/components/InlineError";
import { kindForColumn, type EntityKind } from "@/lib/entity";
import { cn } from "@/lib/cn";
import { fragmentValues, navigate, pathFor, setFragment, useSection } from "@/lib/route";
import { PageHeader } from "@/components/shell/PageHeader";
import { EntityLink } from "@/components/EntityLink";
import { DevicePeople } from "./DevicePeople";
import { DeviceRows } from "./DeviceRows";
import { FollowsRow } from "./FollowsRow";
import { LateBadge } from "./LateBadge";
import { LateRow } from "./LateRow";
import { AroundEvent } from "@/features/search/AroundEvent";
import { When } from "@/components/When";
import { CloseForm } from "./CloseForm";
import { VendorAlerts } from "./VendorAlerts";
import { KIND_LABEL, NAMES_HIDDEN, RESTRICTED_NOTE } from "./kinds";
import { openDrill } from "@/lib/drill";
import { StateNotice } from "@/components/StateNotice";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/Skeleton";
import { since } from "@/features/overview/time";
import { FilterBar } from "@/components/FilterBar";
import { useFilters } from "@/lib/filters";
import { localTime, windowOf, type TimeChoice } from "@/lib/timeWindow";
import { usePageTime } from "@/lib/timeChoice";
import {
  CATEGORY_LABEL,
  guideFor,
  bySeverityThenNewest,
  categoryOf,
  evidenceSql,
  type Category,
} from "./guide";

type Tab = "open" | "closed" | "muted";

interface AlertsPageProps {
  /** Admins and Analysts close and reopen; Auditors read (ADR-0037 row 18). */
  canClose: boolean;
  isAdmin: boolean;
}

type SevFilter = "" | "high" | "medium" | "none";

// Time is for Closed and Muted only, 7 days unless chosen: an open alert never drops out of
// the queue for being old (owner, 2026-11-13).
const FILTER_DEFAULTS = { state: "open", sev: "", cat: "", q: "" };
const SEVERITIES: { id: SevFilter; label: string }[] = [
  { id: "", label: "Any" },
  { id: "high", label: "High" },
  { id: "medium", label: "Medium" },
  { id: "none", label: "None" },
];
const CATEGORIES: { id: string; label: string }[] = [
  { id: "", label: "Any" },
  ...(Object.keys(CATEGORY_LABEL) as Category[]).map((c) => ({ id: c, label: CATEGORY_LABEL[c] })),
];
const FILTER_VALUES = {
  state: ["open", "closed", "muted"],
  sev: SEVERITIES.map((o) => o.id),
  cat: CATEGORIES.map((o) => o.id),
};

/** One queue of everything that fired and needs a decision (ADR-0037, ADR-0043 layout):
 * the list with filters and bulk close and the open alert beside it, across the full width
 * (no summary strip, DESIGN.md 6.2e). `#item=<id>` opens that alert, which is where every alert message
 * links. */
export function AlertsPage({ canClose, isAdmin }: AlertsPageProps) {
  const section = useSection();
  // The fragment holds the State filter and the open alert: `#state=closed&item=<id>`.
  const frag = fragmentValues(section);
  const focus = frag.get("item");
  // The filters live in the fragment too (DESIGN.md 6.0), so a filtered list has an address.
  const filters = useFilters(FILTER_DEFAULTS, FILTER_VALUES);
  const wanted = filters.values.state;
  const tab: Tab = wanted === "closed" || wanted === "muted" ? wanted : "open";
  // `#review`: AI Watch alerts whose service or MCP server is still not reviewed, open
  // and closed (what AI Watch's "not reviewed" count opens; owner, 2026-10-29).
  const reviewing = frag.has("review");
  // The window applies to what was closed in it, and the server picks those (its list is
  // capped, so the browser cannot). Open alerts, and the review list, which holds open ones
  // too, are never filtered by time.
  const timed = tab !== "open" && !reviewing;
  // The time control and its place in the address (UTC times) are the shared ones.
  const time = usePageTime("7d");
  const { choice } = time;
  const list = useQuery({
    // A preset ends now, so the window is worked out when the list is read, not here.
    queryKey: [
      "alerts",
      reviewing ? "unreviewed" : tab === "closed" ? "closed" : "open",
      ...(timed && tab === "closed" ? [choice.preset, choice.from, choice.to] : []),
    ],
    queryFn: () =>
      reviewing
        ? api.unreviewedAlerts()
        : tab === "closed"
          ? api.alerts("closed", windowOf(choice))
          : api.alerts("open"),
  });
  const [picked, setPicked] = useState<string | null>(null);
  const sev = filters.values.sev as SevFilter;
  const cat = filters.values.cat as Category | "";
  // The text box filters as it is typed; the address follows a moment after the last key,
  // so a held key does not rewrite it on every repeat (browsers limit how often).
  const [who, setWho] = useState(filters.values.q);
  useEffect(() => setWho(filters.values.q), [filters.values.q]);
  const latest = useRef(filters);
  latest.current = filters;
  const pending = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(pending.current), []);
  const typeWho = (value: string) => {
    setWho(value);
    window.clearTimeout(pending.current);
    pending.current = window.setTimeout(() => latest.current.set("q", value, true), 300);
  };
  const resetFilters = () => {
    window.clearTimeout(pending.current);
    setWho("");
    // The filters and the time, in one step.
    const next = fragmentValues(section);
    for (const k of [...Object.keys(FILTER_DEFAULTS), "time", "from", "to"]) next.delete(k);
    setFragment(next.toString());
  };
  // "Checked 2 min ago": when this list was last read from the server.
  // The page reads the clock twice a minute, so the text stays true on a page left open.
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  const read = list.dataUpdatedAt || clock;
  const checkedAgo = since(
    new Date(read).toISOString(),
    new Date(Math.max(clock, read)).toISOString(),
  );
  // A new State is a new list: the alert a link opened does not stay beside it.
  const setState = (next: Tab) => {
    const to = fragmentValues(section);
    to.delete("item");
    if (next === "open") to.delete("state");
    else to.set("state", next);
    navigate("alerts", to.toString() || undefined);
  };
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const data = list.data;
  const reasons = data?.reasons ?? ({} as Record<CloseReason, string>);
  // Closed comes newest closed first from the server and stays so; the rest are by
  // severity, then newest.
  const all =
    tab === "closed" && !reviewing
      ? (data?.items ?? [])
      : [...(data?.items ?? [])].sort(bySeverityThenNewest);
  // Every close time kept: Custom with no dates.
  const everything = choice.preset === "custom" && !localTime(choice.from) && !localTime(choice.to);
  const needle = who.trim().toLowerCase();
  const rows = all.filter(
    (i) =>
      (!sev || (sev === "none" ? !i.severity : i.severity === sev)) &&
      (!cat || categoryOf(i) === cat) &&
      (!needle ||
        [i.title, i.subject, i.entity ?? "", ...(i.people ?? []), ...(i.devices ?? [])].some((v) =>
          v.toLowerCase().includes(needle),
        )),
  );
  const current = focus ?? picked ?? rows[0]?.item_id ?? null;
  const pick = (id: string) => {
    setPicked(id);
    if (!focus) return;
    // Leave the linked alert, keeping the filters.
    const rest = fragmentValues(section);
    rest.delete("item");
    navigate("alerts", rest.toString() || undefined);
  };
  // Open, Closed, Muted: the State filter (they were tabs before ADR-0052). The same bar is
  // over the mutes list, so there is always a way back to Open. The count is of the alerts
  // this person can read: the list never holds a restricted one (D243).
  // No zero when some alerts are in sources this person cannot read (DESIGN.md 6.0).
  const openCount = !data || (data.restricted && data.open === 0) ? undefined : data.open;
  const word = (n: number) => (n === 1 ? "alert" : "alerts");
  const bar = (
    <FilterBar
      label="Filter alerts"
      time={timed ? time.bar : undefined}
      state={
        reviewing
          ? undefined
          : {
              value: tab,
              onChange: setState,
              options: [
                { id: "open", label: "Open", count: openCount },
                { id: "closed", label: "Closed" },
                { id: "muted", label: "Muted", count: data?.muted || undefined },
              ],
            }
      }
      facets={
        tab === "muted" && !reviewing
          ? []
          : [
              {
                name: "Severity",
                value: sev,
                options: SEVERITIES,
                onChange: (id) => filters.set("sev", id),
              },
              {
                name: "Category",
                value: cat,
                options: CATEGORIES,
                onChange: (id) => filters.set("cat", id),
              },
            ]
      }
      text={
        tab === "muted" && !reviewing
          ? undefined
          : {
              label: "Person, device, or source",
              value: who,
              onChange: typeWho,
            }
      }
      count={
        // No count over an empty list: with alerts this person cannot read, "0 alerts"
        // would say there are none (DESIGN.md 6.0: no permission is never shown as zero).
        !data || all.length === 0 || (tab === "muted" && !reviewing)
          ? undefined
          : rows.length === all.length
            ? `${all.length} ${word(all.length)}`
            : `${rows.length} of ${all.length} ${word(all.length)}`
      }
      onReset={resetFilters}
      isDefault={
        tab === "open" &&
        !sev &&
        !cat &&
        who === "" &&
        filters.values.q === "" &&
        (!timed || time.isDefault)
      }
    />
  );
  const visibleChecked = rows.filter((i) => checked.has(i.item_id) && i.state === "open");
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader title="Alerts" tabExtras={openCount === undefined ? {} : { Queue: openCount }} />
      <div className="flex min-w-0 flex-col gap-3 px-5 py-4">
        {reviewing ? (
          <p className="text-sm text-text-secondary">
            Not reviewed yet. Closing an alert does not review it: an administrator does.{" "}
            <button
              type="button"
              onClick={() => navigate("alerts")}
              className="text-accent-text hover:underline"
            >
              Back to open alerts
            </button>
          </p>
        ) : null}
        {/* The bar is there in every state of the page (loading, failed, empty), so the
            list never moves under it. */}
        {bar}
        {tab === "muted" && !reviewing ? (
          <MutesList isAdmin={isAdmin} choice={choice} />
        ) : list.isLoading ? (
          // The final layout while loading: the list and the pane.
          <>
            <div className="grid min-w-0 items-start gap-3 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
              <Skeleton label="alerts" rows={6} />
              <Skeleton label="the open alert" rows={4} />
            </div>
          </>
        ) : list.isError && !data ? (
          <div className="rounded-card border border-border bg-surface">
            <InlineError
              what="Alerts"
              error={list.error}
              onRetry={() => void list.refetch()}
              retrying={list.isFetching}
            />
          </div>
        ) : (
          <>
            {canClose && visibleChecked.length > 0 ? (
              <BulkClose
                ids={visibleChecked.map((i) => i.item_id)}
                reasons={reasons}
                onDone={() => setChecked(new Set())}
              />
            ) : null}
            {all.length === 0 && !focus ? (
              <>
                {/* With alerts this person cannot read, no sentence says there are none. */}
                {data?.restricted ? null : timed && !everything ? (
                  <EmptyState
                    kind="filtered"
                    title="No alerts closed in this time window."
                    action={{ label: "Reset filters", onClick: resetFilters }}
                  />
                ) : tab === "open" && !reviewing ? (
                  <EmptyState kind="good-zero" title={`No open alerts. Checked ${checkedAgo}.`} />
                ) : (
                  <EmptyState
                    kind="default-empty"
                    title={reviewing ? "Nothing left to review." : "No closed alerts."}
                  />
                )}
                {/* Nothing listed may only mean nothing this viewer can read (D243). */}
                {data?.restricted ? <StateNotice>{RESTRICTED_NOTE}</StateNotice> : null}
                {tab === "open" && !reviewing ? (
                  <RecentlyClosed canClose={canClose} isAdmin={isAdmin} reasons={reasons} />
                ) : null}
              </>
            ) : (
              <div className="grid min-w-0 items-start gap-3 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
                <ul
                  aria-label="Alert list"
                  className="min-w-0 overflow-hidden rounded-card border border-border bg-surface"
                >
                  {rows.length === 0 ? (
                    <li>
                      <EmptyState
                        kind="filtered"
                        // Only the alert a link named is open: the window itself is empty.
                        title={
                          all.length === 0 && timed
                            ? "No alerts closed in this time window."
                            : "No alerts match these filters."
                        }
                        action={{ label: "Reset filters", onClick: resetFilters }}
                      />
                    </li>
                  ) : null}
                  {rows.map((i) => (
                    <li key={i.item_id} className="border-b border-border last:border-0">
                      <ListRow
                        item={i}
                        current={current === i.item_id}
                        onPick={() => pick(i.item_id)}
                        selectable={canClose && i.state === "open"}
                        checked={checked.has(i.item_id)}
                        onCheck={(on) => {
                          const next = new Set(checked);
                          if (on) next.add(i.item_id);
                          else next.delete(i.item_id);
                          setChecked(next);
                        }}
                      />
                    </li>
                  ))}
                  {data?.restricted ? (
                    <li className="p-2">
                      <StateNotice>{RESTRICTED_NOTE}</StateNotice>
                    </li>
                  ) : null}
                  {data?.capped ? (
                    <li className="p-2">
                      <StateNotice>
                        Only the most recently closed are listed. Choose a shorter time to see the
                        rest.
                      </StateNotice>
                    </li>
                  ) : null}
                </ul>
                <DetailPane
                  id={current}
                  listed={all.find((i) => i.item_id === current) ?? null}
                  canClose={canClose}
                  isAdmin={isAdmin}
                  reasons={reasons}
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function SevBadge({ value }: { value: AlertItem["severity"] }) {
  if (!value) return null;
  return <SeverityMark tone={value} label={value === "high" ? "High" : "Medium"} />;
}

interface ListRowProps {
  item: AlertItem;
  current: boolean;
  onPick: () => void;
  selectable: boolean;
  checked: boolean;
  onCheck: (on: boolean) => void;
}

function ListRow({ item, current, onPick, selectable, checked, onCheck }: ListRowProps) {
  const open = item.state === "open";
  const repeats = item.changes?.length ?? 0;
  return (
    <div className={cn("flex items-start gap-2 px-3 py-2", current && "bg-row-selected")}>
      {selectable ? (
        <input
          type="checkbox"
          aria-label={`Select ${item.title}`}
          checked={checked}
          onChange={(e) => onCheck(e.target.checked)}
          className="mt-1"
        />
      ) : null}
      <button
        type="button"
        aria-current={current ? "true" : undefined}
        onClick={onPick}
        title={item.title}
        className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 text-left text-sm"
      >
        <span className="flex min-w-0 items-start gap-2">
          <SevBadge value={item.severity} />
          <LateBadge late={item.late} start={item.late_start} end={item.late_end} />
          {/* A sentence, not an identity: two lines, then cut, whole in the title (D257). */}
          <span
            data-alert-title=""
            className={cn(
              "line-clamp-2 min-w-0 font-semibold [overflow-wrap:anywhere]",
              !open && "text-text-secondary",
            )}
          >
            {item.title}
          </span>
        </span>
        <When iso={item.last_seen ?? item.created_at} className="shrink-0 text-text-muted" />
        <span className="truncate text-text-secondary">
          {CATEGORY_LABEL[categoryOf(item)]}
          {repeats > 1 ? `, ${repeats + (item.more_changes ?? 0)} changes` : ""}
          {item.count !== null ? `, ${countText(item)}` : ""}
          {item.resolved ? <span className="text-ok">, {item.resolved}</span> : null}
        </span>
        {!open ? <span className="text-text-muted">{item.close_reason_label}</span> : <span />}
      </button>
    </div>
  );
}

/** Close several alerts with one reason (ADR-0043 row 19); each is audited on its own. */
function BulkClose({
  ids,
  reasons,
  onDone,
}: {
  ids: string[];
  reasons: Record<CloseReason, string>;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const [reason, setReason] = useState<CloseReason | "">("");
  const [note, setNote] = useState("");
  const close = useMutation({
    mutationFn: () => api.closeAlerts(ids, reason as CloseReason, note.trim() || null),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["alerts"] });
      onDone();
    },
  });
  const needsNote = reason === "false_positive";
  const ready = reason !== "" && (!needsNote || note.trim().length > 0);
  return (
    <form
      aria-label="Close selected alerts"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) close.mutate();
      }}
      className="flex flex-wrap items-center gap-2 rounded-card border border-border bg-surface-head px-3 py-2 text-sm"
    >
      <span className="font-semibold tabular-nums">{ids.length} selected</span>
      <select
        aria-label="Reason for all selected"
        value={reason}
        onChange={(e) => setReason(e.target.value as CloseReason | "")}
        className="h-8 rounded border border-border-control bg-surface px-2"
      >
        <option value="">Reason</option>
        {(Object.keys(reasons) as CloseReason[]).map((r) => (
          <option key={r} value={r}>
            {reasons[r]}
          </option>
        ))}
      </select>
      <input
        aria-label="Note for all selected"
        placeholder={needsNote ? "Note (required)" : "Note (optional)"}
        value={note}
        maxLength={2000}
        onChange={(e) => setNote(e.target.value)}
        className="h-8 min-w-0 flex-1 rounded border border-border-control bg-inset px-2"
      />
      <button
        type="submit"
        disabled={!ready || close.isPending}
        // Outlined: the page's one filled button is Close in the pane (DESIGN.md 6.0).
        className="h-8 rounded border border-border-strong px-3 font-semibold hover:bg-surface-head disabled:opacity-40"
      >
        Close {ids.length}
      </button>
      <button type="button" onClick={onDone} className="h-8 rounded px-2 hover:bg-surface">
        Clear
      </button>
      {close.data && Object.keys(close.data.skipped).length ? (
        <span role="status" className="text-text-secondary">
          {Object.keys(close.data.skipped).length} not closed
        </span>
      ) : null}
      {close.isError ? (
        <span role="alert" className="text-danger">
          {close.error instanceof ApiError ? close.error.message : "Closing did not work"}
        </span>
      ) : null}
    </form>
  );
}

/** Under an empty queue: the last few decisions, so the page shows what normal looks
 * like (owner, 2026-10-31). */
function RecentlyClosed(props: Omit<DetailProps, "item">) {
  const closed = useQuery({ queryKey: ["alerts", "closed"], queryFn: () => api.alerts("closed") });
  const [openId, setOpenId] = useState<string | null>(null);
  const items = (closed.data?.items ?? []).slice(0, 5);
  if (!items.length) return null;
  return (
    <section aria-label="Recently closed">
      <h2 className="mb-1.5 text-sm font-semibold text-text-secondary">Recently closed</h2>
      <ul className="rounded-card border border-border bg-surface">
        {items.map((i) => (
          <li key={i.item_id} className="border-b border-border last:border-0">
            <ListRow
              item={i}
              current={openId === i.item_id}
              onPick={() => setOpenId(openId === i.item_id ? null : i.item_id)}
              selectable={false}
              checked={false}
              onCheck={() => undefined}
            />
            {openId === i.item_id ? (
              <div className="border-t border-border">
                <AlertDetail item={i} {...props} />
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

interface DetailProps {
  item: AlertItem;
  canClose: boolean;
  isAdmin: boolean;
  reasons: Record<CloseReason, string>;
}

/** The open alert beside the list; one that is not listed (a link to a closed alert) is
 * fetched on its own. */
function DetailPane({
  id,
  listed,
  ...rest
}: Omit<DetailProps, "item"> & { id: string | null; listed: AlertItem | null }) {
  const one = useQuery({
    queryKey: ["alerts", "item", id],
    queryFn: () => api.alert(id ?? ""),
    enabled: id !== null && listed === null,
  });
  const item = listed ?? one.data ?? null;
  return (
    <section
      aria-label="This alert"
      className="min-w-0 rounded-card border border-border bg-surface lg:sticky lg:top-12"
    >
      {item ? (
        // Keyed by the alert: another alert starts with its closed section closed again and
        // no half-filled close form.
        <AlertDetail key={item.item_id} item={item} {...rest} />
      ) : id && one.isError ? (
        <p className="px-3 py-4 text-sm">
          {one.error instanceof ApiError && one.error.status === 403
            ? "This alert read a source you cannot see."
            : "This alert is not there any more, or you cannot see it."}
        </p>
      ) : id ? (
        <Skeleton label="this alert" rows={5} className="rounded-none border-0" />
      ) : (
        <EmptyState kind="default-empty" title="Pick an alert." />
      )}
    </section>
  );
}

function AlertDetail({ item, canClose, isAdmin, reasons }: DetailProps) {
  const client = useQueryClient();
  const [closing, setClosing] = useState(false);
  const reopen = useMutation({
    mutationFn: () => api.reopenAlert(item.item_id),
    onSuccess: () => client.invalidateQueries({ queryKey: ["alerts"] }),
  });
  const mute = useMutation({
    mutationFn: (days: 7 | 30) => api.muteAlert(item.item_id, days),
    onSuccess: () => client.invalidateQueries({ queryKey: ["alerts"] }),
  });
  const guide = guideFor(item);
  const sql = evidenceSql(item);
  const changes = item.changes ?? [];
  // Opens the alert's own events in Logs, an hour either side of what fired. No number on
  // the button: `item.count` is people, runs, or times by kind, never a count of events.
  const showEvents = sql ? (
    <button
      type="button"
      onClick={() =>
        openDrill({
          sql,
          from: new Date(
            new Date(item.range_start ?? item.created_at).getTime() - 3600_000,
          ).toISOString(),
          to: new Date(
            new Date(item.last_seen ?? item.range_end ?? item.created_at).getTime() + 3600_000,
          ).toISOString(),
          origin: `Alerts > ${item.title}`,
        })
      }
      className="h-8 rounded px-2 text-accent-text hover:bg-surface-head hover:underline"
    >
      Show events in Logs
    </button>
  ) : null;
  return (
    <div className="grid gap-4 px-4 py-3 text-sm">
      <header className="grid gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <SevBadge value={item.severity} />
          <LateBadge late={item.late} start={item.late_start} end={item.late_end} />
          <span className="text-text-secondary">{KIND_LABEL[item.kind]}</span>
          <span className="text-text-muted">
            {item.state === "open" ? "Open" : `Closed: ${item.close_reason_label ?? ""}`}
            {item.closed_by ? ` by ${item.closed_by}` : ""}
          </span>
          <span
            className="ml-auto font-mono text-xs text-text-muted"
            title={`Alert ${item.item_id}`}
          >
            {item.item_id.replace(/-/g, "").slice(-8)}
          </span>
        </div>
        <h2 className="text-md">{item.title}</h2>
      </header>
      <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-1">
        <dt className="text-text-muted">What fired</dt>
        <dd className="min-w-0">
          {item.why || item.detail || KIND_LABEL[item.kind]}
          {item.why && item.detail ? (
            <span className="text-text-secondary">. {item.detail}</span>
          ) : null}
          {item.kind === "gap" ? (
            <a
              href={`${pathFor("health")}#source=${encodeURIComponent(item.subject)}`}
              onClick={(e) => {
                e.preventDefault();
                navigate("health", `source=${encodeURIComponent(item.subject)}`);
              }}
              className="ml-2 text-accent-text hover:underline"
            >
              Show on Health
            </a>
          ) : null}
        </dd>
        <FollowsRow follows={item.follows} />
        <LateRow late={item.late} start={item.late_start} end={item.late_end} />
        <dt className="text-text-muted">Why it matters</dt>
        <dd className="text-text-secondary">{guide.why}</dd>
        {item.people?.length ? (
          <>
            <dt className="text-text-muted">People</dt>
            <dd className="font-mono">
              {item.people.map((p, i) => (
                <span key={p}>
                  {i ? " " : ""}
                  <span className="whitespace-nowrap">
                    <EntityLink
                      kind="user"
                      value={p}
                      tab={categoryOf(item) === "ai" ? "ai" : undefined}
                    />
                    {i < (item.people?.length ?? 0) - 1 ? "," : ""}
                  </span>
                </span>
              ))}
            </dd>
          </>
        ) : item.masked && item.people_hidden ? (
          <>
            <dt className="text-text-muted">People</dt>
            <dd className="text-text-secondary">{NAMES_HIDDEN}</dd>
          </>
        ) : null}
        <DeviceRows devices={item.devices ?? []} total={item.devices_total} />
        <DevicePeople found={item.device_people ?? []} masked={item.masked} />
        <dt className="text-text-muted">When</dt>
        <dd>
          First <When iso={item.created_at} />
          {item.last_seen && item.last_seen !== item.created_at ? (
            <>
              , last <When iso={item.last_seen} />
            </>
          ) : null}
          {item.range_start && item.kind === "gap" ? (
            <span className="text-text-secondary">
              {" "}
              (last event <When iso={item.range_start} />)
            </span>
          ) : null}
        </dd>
        {item.resolved ? (
          <>
            <dt className="text-text-muted">Ended</dt>
            <dd className="text-ok">{item.resolved}</dd>
          </>
        ) : null}
        <dt className="text-text-muted">Sources</dt>
        <dd className="font-mono">
          {item.sources.length > 4 ? (
            <span title={item.sources.join(", ")}>{item.sources.length} sources</span>
          ) : (
            item.sources.join(", ") || "·"
          )}
        </dd>
        {item.note ? (
          <>
            <dt className="text-text-muted">Note</dt>
            <dd>{item.note}</dd>
          </>
        ) : null}
        {item.muted_until ? (
          <>
            <dt className="text-text-muted">Muted</dt>
            <dd>
              Alerts like this close themselves until <When iso={item.muted_until} />
            </dd>
          </>
        ) : null}
      </dl>
      {/* The Triage card sits here once it is built (ADR-0049 Phase 1c); empty until then. */}
      <div data-slot="triage" hidden />
      <div className="grid gap-1">
        <h3 className="text-sm font-semibold">Next steps</h3>
        <ol aria-label="Next steps" className="ml-5 grid list-decimal gap-0.5 text-text-secondary">
          {guide.steps.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
      </div>
      {sql && !(canClose && item.state === "open" && !closing) ? <div>{showEvents}</div> : null}
      {canClose ? (
        item.state === "open" ? (
          closing ? (
            <CloseForm
              item={item}
              reasons={reasons}
              isAdmin={isAdmin}
              onDone={() => setClosing(false)}
            />
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setClosing(true)}
                data-primary=""
                className="h-8 rounded bg-accent px-3 font-medium text-on-accent hover:opacity-90"
              >
                Close
              </button>
              {isAdmin ? (
                <>
                  <span className="text-text-muted">Mute similar</span>
                  {([7, 30] as const).map((d) => (
                    <button
                      key={d}
                      type="button"
                      disabled={mute.isPending}
                      onClick={() => mute.mutate(d)}
                      className="h-8 rounded border border-border px-2 hover:bg-surface-head"
                    >
                      {d} days
                    </button>
                  ))}
                </>
              ) : null}
              {showEvents}
            </div>
          )
        ) : (
          <div>
            <button
              type="button"
              disabled={reopen.isPending}
              onClick={() => reopen.mutate()}
              className="h-8 rounded border border-border px-3 hover:bg-surface-head"
            >
              Reopen
            </button>
          </div>
        )
      ) : null}
      {/* Until the full alert page exists (ADR-0049 Phase 1c), what moves there stays here,
          in one section that starts closed, so the pane is slim and nothing is lost (owner,
          2026-11-12). */}
      <details data-more="" className="border-t border-border pt-2">
        <summary className="cursor-pointer select-none text-text-secondary hover:text-text">
          Evidence, changes, and history
        </summary>
        <div className="mt-2 grid gap-4">
          {changes.length ? (
            <div className="grid gap-1">
              <h3 className="text-sm font-semibold">
                Changes today{" "}
                <span className="font-normal text-text-muted">
                  ({changes.length + (item.more_changes ?? 0)}, newest first)
                </span>
              </h3>
              <ul
                aria-label="Changes"
                className="grid gap-0.5 font-mono text-xs text-text-secondary"
              >
                {changes.map((c, n) => (
                  <li key={n} className="[overflow-wrap:anywhere]">
                    {c}
                  </li>
                ))}
                {item.more_changes ? <li>and {item.more_changes} more</li> : null}
              </ul>
            </div>
          ) : null}
          <div className="grid gap-1">
            <h3 className="text-sm font-semibold">Evidence</h3>
            {item.schedule_id && item.ref_id ? (
              <RunRows scheduleId={item.schedule_id} runId={item.ref_id} />
            ) : item.kind === "rule" && item.subject.startsWith("ext:") ? (
              <VendorAlerts itemId={item.item_id} />
            ) : (
              <p className="text-text-muted">
                {sql
                  ? "Its events open in Logs, from the button above."
                  : "No events to show for this alert."}
              </p>
            )}
          </div>
          {/* Closed too: closing never reviewed it (owner, 2026-10-29). */}
          {isAdmin ? <Decide item={item} /> : null}
          {item.history.length ? (
            <ol aria-label="History" className="grid gap-1 text-text-secondary">
              {item.history.map((h, n) => (
                <li key={n}>
                  <When iso={h.at} />{" "}
                  {h.action === "close"
                    ? `Closed by ${h.user ?? "the system"}: ${h.reason_label ?? reasons[h.reason as CloseReason] ?? h.reason}`
                    : `Reopened by ${h.user ?? "the system"}`}
                  {h.note ? <span className="text-text"> ({h.note})</span> : null}
                </li>
              ))}
            </ol>
          ) : null}
        </div>
      </details>
    </div>
  );
}

/** The rows the run kept, with every address, person, and machine a link. */
const SHOWN = 10;

/** An event time as the run kept it ("2026-10-09 20:03:57+00") in ISO form. */
function isoTime(v: unknown): string | null {
  if (typeof v !== "string" || !v) return null;
  return v.replace(" ", "T").replace(/([+-]\d\d)$/, "$1:00");
}

function RunRows({ scheduleId, runId }: { scheduleId: string; runId: string }) {
  const [all, setAll] = useState(false);
  const [around, setAround] = useState<{ id: string; at: string } | null>(null);
  const run = useQuery({
    queryKey: ["schedule-run", scheduleId, runId],
    queryFn: () => api.scheduleRun(scheduleId, runId),
  });
  if (run.isLoading) return <Skeleton label="the run" rows={1} />;
  if (!run.data) return <p className="text-text-muted">The rows of this run are no longer kept.</p>;
  const { columns, sample: kept, truncated, row_count } = run.data;
  const sample = all ? kept : kept.slice(0, SHOWN);
  if (!kept.length) return null;
  const idCol = columns.indexOf("event_id");
  const timeCol = columns.includes("event_time")
    ? columns.indexOf("event_time")
    : columns.indexOf("time");
  const canAround = idCol >= 0 && timeCol >= 0;
  return (
    <div className="min-w-0 overflow-x-auto">
      <table aria-label="Rows that fired" className="w-full text-left font-mono text-xs">
        <thead>
          <tr className="text-text-muted">
            {columns.map((c) => (
              <th key={c} className="px-2 py-1">
                {c}
              </th>
            ))}
            {canAround ? (
              <th className="px-2 py-1">
                <span className="sr-only">Around</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {sample.map((row, r) => (
            <tr key={r} className="border-t border-border">
              {row.map((cell, j) => {
                const kind = kindForColumn(columns[j] ?? "");
                return (
                  <td key={j} className="px-2 py-1">
                    {kind ? (
                      <EntityLink kind={kind as EntityKind} value={cell} />
                    ) : (
                      String(cell ?? "")
                    )}
                  </td>
                );
              })}
              {canAround ? (
                <td className="px-2 py-1 font-sans">
                  {isoTime(row[timeCol]) ? (
                    <button
                      type="button"
                      aria-pressed={around?.id === String(row[idCol])}
                      onClick={() => {
                        const id = String(row[idCol]);
                        const at = isoTime(row[timeCol]) as string;
                        setAround(around?.id === id ? null : { id, at });
                      }}
                      className="text-accent-text hover:underline"
                    >
                      Around
                    </button>
                  ) : null}
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
      {around ? (
        <div className="mt-2 font-sans">
          <AroundEvent eventId={around.id} at={around.at} />
        </div>
      ) : null}
      <p className="mt-1 text-text-muted">
        {sample.length < kept.length ? (
          <button
            type="button"
            onClick={() => setAll(true)}
            className="text-accent-text hover:underline"
          >
            Show all {kept.length} kept rows
          </button>
        ) : truncated ? (
          `The first ${kept.length} of ${(row_count ?? 0).toLocaleString()} rows were kept.`
        ) : null}
      </p>
    </div>
  );
}

interface MutesListProps {
  isAdmin: boolean;
  /** The page's time choice. Mutes in force are always listed; the window adds those that
   * were in force at some point in it and have ended. */
  choice: TimeChoice;
}

function MutesList({ isAdmin, choice }: MutesListProps) {
  const client = useQueryClient();
  const mutes = useQuery({
    queryKey: ["alerts", "mutes", choice.preset, choice.from, choice.to],
    queryFn: () => api.alertMutes(windowOf(choice)),
  });
  const unmute = useMutation({
    mutationFn: api.unmuteAlert,
    onSuccess: () => client.invalidateQueries({ queryKey: ["alerts"] }),
  });
  if (mutes.isLoading) return <Skeleton label="mutes" rows={2} />;
  // Only when there is nothing to show: a failed refresh keeps the mutes already listed.
  if (mutes.isError && !mutes.data)
    return (
      <div className="rounded-card border border-border bg-surface">
        <InlineError
          what="Mutes"
          error={mutes.error}
          onRetry={() => void mutes.refetch()}
          retrying={mutes.isFetching}
        />
      </div>
    );
  const listed = mutes.data ?? [];
  if (!listed.length)
    return (
      <EmptyState
        kind="default-empty"
        title="Nothing is muted."
        detail="No mute ended in this time window."
      />
    );
  return (
    <ul className="rounded-card border border-border bg-surface text-sm">
      {listed.map((m) => (
        <li
          key={m.mute_id}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-3 py-2 last:border-0"
        >
          <span className="font-semibold">{m.title}</span>
          <span className="text-text-secondary">{KIND_LABEL[m.kind]}</span>
          <span className="text-text-secondary">
            {m.active === false ? (
              <>
                ended <When iso={m.ended_at ?? m.until} />
              </>
            ) : (
              <>
                until <When iso={m.until} />
              </>
            )}
            {m.created_by ? `, by ${m.created_by}` : ""}
          </span>
          {isAdmin && m.active !== false ? (
            <button
              type="button"
              aria-label={`Unmute ${m.title}`}
              disabled={unmute.isPending}
              onClick={() => unmute.mutate(m.mute_id)}
              className="ml-auto h-7 rounded border border-border px-2 hover:bg-surface-head"
            >
              Unmute
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** Approve or mark not approved, from a review item (ADR-0035 row 11): the same admin-only
 * review as AI usage, which closes the item with that decision. */
function Decide({ item }: { item: AlertItem }) {
  const client = useQueryClient();
  const [kind, ...rest] = item.subject.split(":");
  const name = rest.join(":");
  const decide = useMutation({
    mutationFn: async (status: "approved" | "not_approved") => {
      if (kind === "service") await api.setAiServiceStatus(name, status);
      else await api.setAiMcpRule(name, status);
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["alerts"] });
      await client.invalidateQueries({ queryKey: ["ai-watch"] });
      await client.invalidateQueries({ queryKey: ["ai-usage"] });
    },
  });
  if (item.kind !== "ai_watch" || (kind !== "service" && kind !== "mcp")) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-text-secondary">
        {kind === "service" ? "This service" : "This MCP server"}:
      </span>
      <button
        type="button"
        disabled={decide.isPending}
        onClick={() => decide.mutate("approved")}
        className="h-8 rounded border border-border px-3 hover:bg-surface-head"
      >
        Approve
      </button>
      <button
        type="button"
        disabled={decide.isPending}
        onClick={() => decide.mutate("not_approved")}
        className="h-8 rounded border border-border px-3 hover:bg-surface-head"
      >
        Not approved
      </button>
      {decide.isError ? (
        <span role="alert" className="text-danger">
          {decide.error instanceof ApiError ? decide.error.message : "That did not work"}
        </span>
      ) : null}
    </div>
  );
}

/** What a count is, by kind: rows a run returned, who used an AI service, or signals. */
function countText(item: AlertItem): string {
  const n = (item.count ?? 0).toLocaleString();
  if (item.rule === "blocked_calls")
    return `${n} blocked or failed ${item.count === 1 ? "call" : "calls"}`;
  if (item.kind === "gap" || item.rule === "agent_change" || item.rule === "agent_busy")
    return `${n} ${item.count === 1 ? "time" : "times"} today`;
  if (item.kind !== "ai_watch") return `${n} ${item.count === 1 ? "row" : "rows"}`;
  if (item.subject.startsWith("sensitive:"))
    return `${n} ${item.count === 1 ? "signal" : "signals"}`;
  // People only: devices with no person are named in the detail, never added in.
  return item.count ? `${n} ${item.count === 1 ? "person" : "people"}` : "no person matched";
}
