import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, type AlertItem, type CloseReason } from "@/lib/api";
import { kindForColumn, type EntityKind } from "@/lib/entity";
import { cn } from "@/lib/cn";
import { navigate, pathFor, useSection } from "@/lib/route";
import { EntityLink } from "@/components/EntityLink";
import { When } from "@/components/When";
import { CloseForm } from "./CloseForm";
import { KIND_LABEL } from "./kinds";

type Tab = "open" | "closed" | "muted";

interface AlertsPageProps {
  /** Admins and Analysts close and reopen; Auditors read (ADR-0037 row 18). */
  canClose: boolean;
  isAdmin: boolean;
}

/** One queue of everything that fired and needs a decision (ADR-0037). `#item=<id>` opens
 * that alert, which is where every alert message links. */
export function AlertsPage({ canClose, isAdmin }: AlertsPageProps) {
  const section = useSection();
  const focus = section.startsWith("item=") ? decodeURIComponent(section.slice(5)) : null;
  const tab: Tab = section === "closed" || section === "muted" ? section : "open";
  const setTab = (t: Tab) => navigate("alerts", t === "open" ? undefined : t);
  const list = useQuery({
    queryKey: ["alerts", tab === "closed" ? "closed" : "open"],
    queryFn: () => api.alerts(tab === "closed" ? "closed" : "open"),
  });
  const focused = useQuery({
    queryKey: ["alerts", "item", focus],
    queryFn: () => api.alert(focus ?? ""),
    enabled: focus !== null,
  });
  const [openId, setOpenId] = useState<string | null>(null);
  const data = list.data;
  const reasons = data?.reasons ?? ({} as Record<CloseReason, string>);
  const rowProps = { canClose, isAdmin, reasons };
  return (
    <div className="mx-auto w-full max-w-5xl min-w-0 p-4">
      <h1 className="text-lg font-semibold">Alerts</h1>
      <p className="mb-3 text-sm text-text-secondary">
        Everything that fired and needs a decision. Close each one with a reason.
      </p>
      {focus ? (
        <section aria-label="This alert" className="mb-4">
          {focused.data ? (
            <AlertRow
              item={focused.data}
              expanded
              onToggle={() => navigate("alerts")}
              {...rowProps}
            />
          ) : focused.isError ? (
            <p className="rounded-card border border-border bg-surface px-3 py-2 text-sm">
              {focused.error instanceof ApiError && focused.error.status === 403
                ? "This alert read a source you cannot see."
                : "This alert is not there any more, or you cannot see it."}
            </p>
          ) : (
            <div className="h-12 animate-pulse rounded-card bg-surface" aria-busy="true" />
          )}
        </section>
      ) : null}
      <div role="tablist" aria-label="Alerts" className="mb-2 flex gap-1 border-b border-border">
        {(["open", "closed", "muted"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            className={cn(
              "-mb-px border-b-2 px-3 py-1.5 text-sm",
              tab === t
                ? "border-accent font-semibold text-accent-text"
                : "border-transparent text-text-secondary hover:text-text",
            )}
          >
            {t === "open" ? "Open" : t === "closed" ? "Closed" : "Muted"}
            {t === "open" && data ? (
              <span className="ml-1.5 font-mono tabular-nums text-text-muted">{data.open}</span>
            ) : null}
            {t === "muted" && data?.muted ? (
              <span className="ml-1.5 font-mono tabular-nums text-text-muted">{data.muted}</span>
            ) : null}
          </button>
        ))}
      </div>
      {tab === "muted" ? (
        <MutesList isAdmin={isAdmin} />
      ) : list.isLoading ? (
        <div className="h-24 animate-pulse rounded-card bg-surface" aria-busy="true" />
      ) : list.isError ? (
        <p role="alert" className="text-sm text-danger">
          Alerts did not load. {list.error instanceof ApiError ? list.error.message : ""}
        </p>
      ) : (
        <>
          {tab === "open" && data && data.muted > 0 ? (
            <p className="mb-2 text-sm text-text-secondary">
              <button
                type="button"
                onClick={() => setTab("muted")}
                className="text-accent-text hover:underline"
              >
                {data.muted} muted
              </button>
              : new alerts like those close themselves until the mute ends.
            </p>
          ) : null}
          {data && data.restricted > 0 && tab === "open" ? (
            <p className="mb-2 text-sm text-text-secondary">
              {data.restricted} restricted: {data.restricted === 1 ? "it read" : "they read"} a
              source you cannot see.
            </p>
          ) : null}
          {data && data.items.length === 0 ? (
            <p className="rounded-card border border-border bg-surface px-3 py-6 text-center text-sm text-text-secondary">
              {tab === "open"
                ? "Nothing needs a decision. New flagged runs, rule matches, and gaps on sources with Alert if quiet on land here."
                : "Nothing closed yet."}
            </p>
          ) : (
            <ul className="rounded-card border border-border bg-surface">
              {data?.items.map((i) => (
                <li key={i.item_id} className="border-b border-border last:border-0">
                  <AlertRow
                    item={i}
                    expanded={openId === i.item_id}
                    onToggle={() => setOpenId(openId === i.item_id ? null : i.item_id)}
                    {...rowProps}
                  />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

interface AlertRowProps {
  item: AlertItem;
  expanded: boolean;
  onToggle: () => void;
  canClose: boolean;
  isAdmin: boolean;
  reasons: Record<CloseReason, string>;
}

function AlertRow({ item, expanded, onToggle, ...rest }: AlertRowProps) {
  const open = item.state === "open";
  return (
    <div className={cn(expanded && "bg-surface")}>
      <button
        type="button"
        aria-expanded={expanded}
        onClick={onToggle}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-left text-sm hover:bg-surface-head"
      >
        <span
          aria-hidden="true"
          className={cn("h-4 w-1 shrink-0 rounded", open ? "bg-warn" : "bg-border")}
        />
        {item.severity ? (
          <span
            className={cn(
              "rounded-badge px-1.5 text-xs font-semibold",
              item.severity === "high"
                ? "bg-sev-high-bg text-sev-high-text"
                : "bg-sev-medium-bg text-sev-medium-text",
            )}
          >
            {item.severity === "high" ? "High" : "Medium"}
          </span>
        ) : null}
        <span className="min-w-0 font-semibold">{item.title}</span>
        <span className="text-text-secondary">{KIND_LABEL[item.kind]}</span>
        {item.count !== null ? (
          <span className="tabular-nums text-text-secondary">{countText(item)}</span>
        ) : null}
        {item.resolved ? <span className="text-ok">{item.resolved}</span> : null}
        {!open ? (
          <span className="text-text-muted">
            Closed: {item.close_reason_label}
            {item.closed_by ? ` by ${item.closed_by}` : ""}
          </span>
        ) : null}
        <When iso={item.created_at} className="ml-auto shrink-0 text-text-muted" />
      </button>
      {expanded ? <AlertDetail item={item} {...rest} /> : null}
    </div>
  );
}

function AlertDetail({
  item,
  canClose,
  isAdmin,
  reasons,
}: Omit<AlertRowProps, "expanded" | "onToggle">) {
  const client = useQueryClient();
  const [closing, setClosing] = useState(false);
  const reopen = useMutation({
    mutationFn: () => api.reopenAlert(item.item_id),
    onSuccess: () => client.invalidateQueries({ queryKey: ["alerts"] }),
  });
  return (
    <div className="grid gap-3 border-t border-border px-3 py-3 text-sm">
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
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
        {item.range_start ? (
          <>
            <dt className="text-text-muted">{item.kind === "gap" ? "Last event" : "Range"}</dt>
            <dd>
              <When iso={item.range_start} />
              {item.range_end ? (
                <>
                  {" to "}
                  <When iso={item.range_end} />
                </>
              ) : null}
            </dd>
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
        {item.state === "closed" ? (
          <>
            <dt className="text-text-muted">Closed</dt>
            <dd>
              {item.close_reason_label}
              {item.closed_by ? ` by ${item.closed_by}` : ""}
              {item.note ? <span className="text-text-secondary">: {item.note}</span> : null}
            </dd>
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
      {isAdmin && item.state === "open" ? <Decide item={item} /> : null}
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
            <div>
              <button
                type="button"
                onClick={() => setClosing(true)}
                className="h-8 rounded border border-border px-3 hover:bg-surface-head"
              >
                Close
              </button>
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
      {item.schedule_id && item.ref_id ? (
        <RunRows scheduleId={item.schedule_id} runId={item.ref_id} />
      ) : null}
      {item.history.length ? (
        <ol aria-label="History" className="grid gap-1 text-text-secondary">
          {item.history.map((h, n) => (
            <li key={n}>
              <When iso={h.at} />{" "}
              {h.action === "close"
                ? `Closed by ${h.user ?? "the system"}: ${reasons[h.reason as CloseReason] ?? (h.reason === "muted" ? "Muted" : h.reason)}`
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

function RunRows({ scheduleId, runId }: { scheduleId: string; runId: string }) {
  const [all, setAll] = useState(false);
  const run = useQuery({
    queryKey: ["schedule-run", scheduleId, runId],
    queryFn: () => api.scheduleRun(scheduleId, runId),
  });
  if (run.isLoading) return <div className="h-12 animate-pulse rounded bg-surface-head" />;
  if (!run.data) return <p className="text-text-muted">The rows of this run are no longer kept.</p>;
  const { columns, sample: kept, truncated, row_count } = run.data;
  const sample = all ? kept : kept.slice(0, SHOWN);
  if (!kept.length) return null;
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
            </tr>
          ))}
        </tbody>
      </table>
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
        Nothing is muted. An administrator can mute alerts like one they close, for up to 30 days.
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
    onSuccess: () => client.invalidateQueries({ queryKey: ["alerts"] }),
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
  if (item.kind !== "ai_watch") return `${n} ${item.count === 1 ? "row" : "rows"}`;
  if (item.subject.startsWith("sensitive:"))
    return `${n} ${item.count === 1 ? "signal" : "signals"}`;
  return `used by ${n}`;
}
