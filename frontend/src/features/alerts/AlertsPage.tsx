import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, type AlertItem, type CloseReason } from "@/lib/api";
import { LoadFailed } from "@/components/LoadFailed";
import { kindForColumn, type EntityKind } from "@/lib/entity";
import { cn } from "@/lib/cn";
import { navigate, pathFor, useSection, useSectionTab } from "@/lib/route";
import { PageHeader } from "@/components/shell/PageHeader";
import { EntityLink } from "@/components/EntityLink";
import { AroundEvent } from "@/features/search/AroundEvent";
import { When } from "@/components/When";
import { CloseForm } from "./CloseForm";
import { KIND_LABEL } from "./kinds";
import { openDrill } from "@/lib/drill";
import {
  CATEGORY_LABEL,
  GUIDE,
  bySeverityThenNewest,
  categoryOf,
  evidenceSql,
  ruleOf,
  summarize,
  type Category,
  type Summary,
} from "./guide";

type Tab = "open" | "closed" | "muted";

interface AlertsPageProps {
  /** Admins and Analysts close and reopen; Auditors read (ADR-0037 row 18). */
  canClose: boolean;
  isAdmin: boolean;
}

type SevFilter = "" | "high" | "medium" | "none";

/** One queue of everything that fired and needs a decision (ADR-0037, ADR-0043 layout): a
 * summary strip, the list with filters and bulk close, and the open alert beside it, all
 * across the full width. `#item=<id>` opens that alert, which is where every alert message
 * links. */
export function AlertsPage({ canClose, isAdmin }: AlertsPageProps) {
  const section = useSection();
  const focus = section.startsWith("item=") ? decodeURIComponent(section.slice(5)) : null;
  const [tab, setTab] = useSectionTab<Tab>(["open", "closed", "muted"]);
  // `#review`: AI Watch alerts whose service or MCP server is still not reviewed, open
  // and closed (what AI Watch's "not reviewed" count opens; owner, 2026-10-29).
  const reviewing = section === "review";
  const list = useQuery({
    queryKey: ["alerts", reviewing ? "unreviewed" : tab === "closed" ? "closed" : "open"],
    queryFn: () =>
      reviewing ? api.unreviewedAlerts() : api.alerts(tab === "closed" ? "closed" : "open"),
  });
  const [picked, setPicked] = useState<string | null>(null);
  const [sev, setSev] = useState<SevFilter>("");
  const [cat, setCat] = useState<Category | "">("");
  const [who, setWho] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const data = list.data;
  const reasons = data?.reasons ?? ({} as Record<CloseReason, string>);
  const all = [...(data?.items ?? [])].sort(bySeverityThenNewest);
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
    if (focus) navigate("alerts");
  };
  const summary = summarize(all);
  const filtered = rows.length !== all.length;
  const visibleChecked = rows.filter((i) => checked.has(i.item_id) && i.state === "open");
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        title="Alerts"
        meta="Everything that fired and needs a decision. Close each one with a reason."
        tabExtras={{
          ...(data ? { Open: data.open } : {}),
          ...(data?.muted ? { Muted: data.muted } : {}),
        }}
      />
      <div className="flex min-w-0 flex-col gap-3 p-4">
        {reviewing ? (
          <p className="text-sm text-text-secondary">
            AI services and MCP servers still not reviewed, with their alerts open and closed.
            Closing an alert does not review it: open one and choose Approve or Not approved, close
            it as Approved, or set it on AI usage.{" "}
            <button
              type="button"
              onClick={() => navigate("alerts")}
              className="text-accent-text hover:underline"
            >
              Back to open alerts
            </button>
          </p>
        ) : null}
        {tab === "muted" && !reviewing ? (
          <MutesList isAdmin={isAdmin} />
        ) : list.isLoading ? (
          <div className="h-24 animate-pulse rounded-card bg-surface" aria-busy="true" />
        ) : list.isError ? (
          <div className="rounded-card border border-border bg-surface">
            <LoadFailed
              what="Alerts"
              error={list.error}
              onRetry={() => void list.refetch()}
              retrying={list.isFetching}
            />
          </div>
        ) : (
          <>
            {tab === "open" && !reviewing ? (
              <SummaryStrip
                summary={summary}
                restricted={data?.restricted ?? 0}
                muted={data?.muted ?? 0}
                onSeverity={(v) => setSev(sev === v ? "" : v)}
                onCategory={(v) => setCat(cat === v ? "" : v)}
                onOldest={(id) => pick(id)}
                onMuted={() => setTab("muted")}
              />
            ) : null}
            <div
              role="group"
              aria-label="Filter alerts"
              className="flex flex-wrap items-center gap-2 text-sm"
            >
              <select
                aria-label="Severity"
                value={sev}
                onChange={(e) => setSev(e.target.value as SevFilter)}
                className="h-8 rounded border border-border-strong bg-surface px-2"
              >
                <option value="">Any severity</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="none">No severity</option>
              </select>
              <select
                aria-label="Category"
                value={cat}
                onChange={(e) => setCat(e.target.value as Category | "")}
                className="h-8 rounded border border-border-strong bg-surface px-2"
              >
                <option value="">Any category</option>
                {(Object.keys(CATEGORY_LABEL) as Category[]).map((c) => (
                  <option key={c} value={c}>
                    {CATEGORY_LABEL[c]}
                  </option>
                ))}
              </select>
              <input
                aria-label="Person, device, or source"
                placeholder="Person, device, or source"
                value={who}
                onChange={(e) => setWho(e.target.value)}
                className="h-8 w-56 min-w-0 rounded border border-border-strong bg-inset px-2"
              />
              {filtered ? (
                <span className="tabular-nums text-text-muted">
                  {rows.length} of {all.length} shown
                </span>
              ) : null}
            </div>
            {canClose && visibleChecked.length > 0 ? (
              <BulkClose
                ids={visibleChecked.map((i) => i.item_id)}
                reasons={reasons}
                onDone={() => setChecked(new Set())}
              />
            ) : null}
            {all.length === 0 ? (
              <>
                <p className="rounded-card border border-border bg-surface px-3 py-6 text-center text-sm text-text-secondary">
                  {tab === "open"
                    ? "Nothing needs a decision. New flagged runs, rule matches, and gaps on sources with Alert if quiet on land here."
                    : "Nothing closed yet."}
                </p>
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
                    <li className="px-3 py-6 text-center text-sm text-text-secondary">
                      No alerts match these filters.
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
  return (
    <span
      className={cn(
        "rounded-badge px-1.5 text-xs font-semibold",
        value === "high"
          ? "bg-sev-high-bg text-sev-high-text"
          : "bg-sev-medium-bg text-sev-medium-text",
      )}
    >
      {value === "high" ? "High" : "Medium"}
    </span>
  );
}

interface SummaryStripProps {
  summary: Summary;
  restricted: number;
  muted: number;
  onSeverity: (v: SevFilter) => void;
  onCategory: (v: Category) => void;
  onOldest: (id: string) => void;
  onMuted: () => void;
}

/** Open alerts at a glance (ADR-0043 layout): by severity, new today, the oldest still
 * open, and by category. Each figure filters the list. */
function SummaryStrip({ summary: s, restricted, muted, ...on }: SummaryStripProps) {
  const cell = "flex min-w-0 flex-col gap-1 px-4 py-2.5";
  const label = "text-xs text-text-muted";
  return (
    <section
      aria-label="Open alerts summary"
      className="grid min-w-0 divide-y divide-border rounded-card border border-border bg-surface sm:grid-cols-2 sm:divide-y-0 xl:grid-cols-[auto_auto_minmax(0,1fr)_auto] xl:divide-x"
    >
      <div className={cell}>
        <span className={label}>Open by severity</span>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <button
            type="button"
            onClick={() => on.onSeverity("high")}
            className="flex items-center gap-1.5 hover:underline"
          >
            <SevBadge value="high" />
            <span className="font-mono tabular-nums">{s.high}</span>
          </button>
          <button
            type="button"
            onClick={() => on.onSeverity("medium")}
            className="flex items-center gap-1.5 hover:underline"
          >
            <SevBadge value="medium" />
            <span className="font-mono tabular-nums">{s.medium}</span>
          </button>
          <button
            type="button"
            onClick={() => on.onSeverity("none")}
            className="flex items-center gap-1.5 text-text-secondary hover:underline"
          >
            Other <span className="font-mono tabular-nums text-text">{s.other}</span>
          </button>
        </div>
      </div>
      <div className={cell}>
        <span className={label}>New today</span>
        <span className="font-mono text-lg tabular-nums">{s.newToday}</span>
      </div>
      <div className={cell}>
        <span className={label}>Oldest open</span>
        {s.oldest ? (
          <button
            type="button"
            onClick={() => s.oldest && on.onOldest(s.oldest.item_id)}
            className="min-w-0 truncate text-left text-sm text-accent-text hover:underline"
            title={s.oldest.title}
          >
            <When iso={s.oldest.created_at} />: {s.oldest.title}
          </button>
        ) : (
          <span className="text-sm text-text-muted">None</span>
        )}
      </div>
      <div className={cell}>
        <span className={label}>By category</span>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
          {(Object.keys(CATEGORY_LABEL) as Category[]).map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => on.onCategory(c)}
              className="text-text-secondary hover:underline"
            >
              {CATEGORY_LABEL[c]}{" "}
              <span className="font-mono tabular-nums text-text">{s.categories[c]}</span>
            </button>
          ))}
        </div>
        {restricted > 0 || muted > 0 ? (
          <span className="text-xs text-text-muted">
            {restricted > 0 ? `${restricted} restricted (a source you cannot see)` : ""}
            {restricted > 0 && muted > 0 ? ", " : ""}
            {muted > 0 ? (
              <button
                type="button"
                onClick={on.onMuted}
                className="text-accent-text hover:underline"
              >
                {muted} muted
              </button>
            ) : null}
          </span>
        ) : null}
      </div>
    </section>
  );
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
        className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 text-left text-sm"
      >
        <span className="flex min-w-0 items-center gap-2">
          <SevBadge value={item.severity} />
          <span className={cn("truncate font-semibold", !open && "text-text-secondary")}>
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
        className="h-8 rounded border border-border-strong bg-surface px-2"
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
        className="h-8 min-w-0 flex-1 rounded border border-border-strong bg-inset px-2"
      />
      <button
        type="submit"
        disabled={!ready || close.isPending}
        className="h-8 rounded bg-accent px-3 font-semibold text-white disabled:opacity-40"
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
        <AlertDetail item={item} {...rest} />
      ) : id && one.isError ? (
        <p className="px-3 py-4 text-sm">
          {one.error instanceof ApiError && one.error.status === 403
            ? "This alert read a source you cannot see."
            : "This alert is not there any more, or you cannot see it."}
        </p>
      ) : id ? (
        <div className="h-40 animate-pulse" aria-busy="true" />
      ) : (
        <p className="px-3 py-6 text-center text-sm text-text-secondary">Pick an alert.</p>
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
  const rule = ruleOf(item);
  const guide = GUIDE[rule];
  const sql = evidenceSql(item);
  const changes = item.changes ?? [];
  return (
    <div className="grid gap-4 px-4 py-3 text-sm">
      <header className="grid gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <SevBadge value={item.severity} />
          <span className="text-text-secondary">{KIND_LABEL[item.kind]}</span>
          <span className="text-text-muted">
            {item.state === "open" ? "Open" : `Closed: ${item.close_reason_label ?? ""}`}
            {item.closed_by ? ` by ${item.closed_by}` : ""}
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
        <dt className="text-text-muted">Why it matters</dt>
        <dd className="text-text-secondary">{guide.why}</dd>
        {item.people?.length ? (
          <>
            <dt className="text-text-muted">People</dt>
            <dd className="font-mono">
              {item.people.map((p, i) => (
                <span key={p}>
                  {i ? ", " : ""}
                  <EntityLink
                    kind="user"
                    value={p}
                    tab={categoryOf(item) === "ai" ? "ai" : undefined}
                  />
                </span>
              ))}
            </dd>
          </>
        ) : null}
        {item.devices?.length ? (
          <>
            <dt className="text-text-muted">Devices</dt>
            <dd className="font-mono">
              {item.devices.map((d, i) => (
                <span key={d}>
                  {i ? ", " : ""}
                  <EntityLink kind="host" value={d} />
                </span>
              ))}
            </dd>
          </>
        ) : null}
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
      {changes.length ? (
        <div className="grid gap-1">
          <h3 className="text-sm font-semibold">
            Changes today{" "}
            <span className="font-normal text-text-muted">
              ({changes.length + (item.more_changes ?? 0)}, newest first)
            </span>
          </h3>
          <ul aria-label="Changes" className="grid gap-0.5 font-mono text-xs text-text-secondary">
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
        {sql ? (
          <div>
            <button
              type="button"
              onClick={() =>
                openDrill({
                  sql,
                  from: new Date(
                    new Date(item.range_start ?? item.created_at).getTime() - 3600_000,
                  ).toISOString(),
                  to: new Date(
                    new Date(item.last_seen ?? item.range_end ?? item.created_at).getTime() +
                      3600_000,
                  ).toISOString(),
                  origin: `Alerts > ${item.title}`,
                })
              }
              className="text-accent-text hover:underline"
            >
              Show events
            </button>
          </div>
        ) : null}
        {item.schedule_id && item.ref_id ? (
          <RunRows scheduleId={item.schedule_id} runId={item.ref_id} />
        ) : !sql ? (
          <p className="text-text-muted">No events to show for this alert.</p>
        ) : null}
      </div>
      <div className="grid gap-1">
        <h3 className="text-sm font-semibold">Next steps</h3>
        <ol aria-label="Next steps" className="ml-5 grid list-decimal gap-0.5 text-text-secondary">
          {guide.steps.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
      </div>
      {/* Closed too: closing never reviewed it (owner, 2026-10-29). */}
      {isAdmin ? <Decide item={item} /> : null}
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
                className="h-8 rounded border border-border-strong px-3 hover:bg-surface-head"
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
  if (run.isLoading) return <div className="h-12 animate-pulse rounded bg-surface-head" />;
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
              <th key={c} className="px-2 py-1 font-normal">
                {c}
              </th>
            ))}
            {canAround ? (
              <th className="px-2 py-1 font-normal">
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

function MutesList({ isAdmin }: { isAdmin: boolean }) {
  const client = useQueryClient();
  const mutes = useQuery({ queryKey: ["alerts", "mutes"], queryFn: api.alertMutes });
  const unmute = useMutation({
    mutationFn: api.unmuteAlert,
    onSuccess: () => client.invalidateQueries({ queryKey: ["alerts"] }),
  });
  if (mutes.isLoading) return <div className="h-12 animate-pulse rounded-card bg-surface" />;
  if (!mutes.data?.length)
    return (
      <p className="rounded-card border border-border bg-surface px-3 py-6 text-center text-sm text-text-secondary">
        Nothing is muted. An administrator can mute alerts like one they close, for 7 or 30 days.
      </p>
    );
  return (
    <ul className="rounded-card border border-border bg-surface text-sm">
      {mutes.data.map((m) => (
        <li
          key={m.mute_id}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-3 py-2 last:border-0"
        >
          <span className="font-semibold">{m.title}</span>
          <span className="text-text-secondary">{KIND_LABEL[m.kind]}</span>
          <span className="text-text-secondary">
            until <When iso={m.until} />
            {m.created_by ? `, by ${m.created_by}` : ""}
          </span>
          {isAdmin ? (
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
