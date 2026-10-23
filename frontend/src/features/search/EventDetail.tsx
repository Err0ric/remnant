import { useQuery } from "@tanstack/react-query";
import { useContext } from "react";
import { api, type Cell, type GeoInfo, type IntelHit } from "@/lib/api";
import { intelLine } from "@/lib/intel";
import { geoLong } from "@/lib/geo";
import { FieldActionsContext } from "./fieldActions";
import { AddressHolders } from "./AddressHolders";
import { FieldButton } from "./FieldButton";
import { ENTITY_COLUMNS, type InvestigateSeed } from "@/lib/investigateSeed";
import { EntityLink } from "@/components/EntityLink";
import { kindForColumn, openEntity, type EntityKind } from "@/lib/entity";
import { eventSql, formatCell } from "@/lib/search";

interface EventDetailProps {
  columns: string[];
  row: Cell[];
  /** Present when the results can be explained: this event's place in the selection. */
  selection?: { selected: boolean; toggle: () => void };
  /** Location of public addresses, when the viewer shows it (ADR-0023 row 6). */
  geo?: Record<string, GeoInfo>;
  /** Values listed in threat intel (ADR-0023 row 7). */
  intel?: Record<string, IntelHit[]>;
}

// Fields shown first when the full event is available; the rest follow alphabetically.
const PRIORITY = [
  "time",
  "source_id",
  "device_hostname",
  "actor_user_name",
  "actor_process_name",
  "actor_process_pid",
  "src_endpoint_ip",
  "src_endpoint_port",
  "dst_endpoint_ip",
  "dst_endpoint_port",
  "class_uid",
  "status_id",
  "parse_status",
  "parse_errors",
  "template_id",
  "classification",
  "event_id",
];
const HIDDEN = new Set([
  "raw",
  "envelope",
  "unmapped",
  "message",
  "severity_id",
  "time_observed",
  "owner_id",
  "template_version",
  "raw_bytes_invalid",
  "category_uid",
  "activity_id",
]);

export function EventDetail({ columns, row, selection, geo, intel }: EventDetailProps) {
  const idIndex = columns.indexOf("event_id");
  const eventId = idIndex >= 0 ? String(row[idIndex] ?? "") : "";
  const sql = eventId ? eventSql(eventId) : null;
  const full = useQuery({
    queryKey: ["event", eventId],
    queryFn: () => api.query({ sql: sql ?? "" }),
    enabled: sql !== null,
  });

  const source = full.data?.rows[0]
    ? { columns: full.data.columns, row: full.data.rows[0] }
    : { columns, row };
  const record: Record<string, Cell> = Object.fromEntries(
    source.columns.map((c, i) => [c, source.row[i] ?? null]),
  );
  const fields = [
    ...PRIORITY.filter((k) => k in record && record[k] !== null && record[k] !== ""),
    ...Object.keys(record)
      .filter(
        (k) => !PRIORITY.includes(k) && !HIDDEN.has(k) && record[k] !== null && record[k] !== "",
      )
      .sort(),
  ];
  const raw = record.raw;
  // The full event's lookup covers every field; the row's covers the columns shown.
  const places = geo ? { ...geo, ...(full.data?.geo ?? {}) } : undefined;
  const placeOf = (v: Cell | undefined) =>
    places && typeof v === "string" ? places[v] : undefined;
  const listed = { ...(intel ?? {}), ...(full.data?.intel ?? {}) };
  const hitsOf = (v: Cell | undefined) => (typeof v === "string" ? listed[v] : undefined);
  const actions = useContext(FieldActionsContext);
  const local = record.classification === "local_only";
  // The header's Investigate opens the first person, address, or host on the event.
  const focusKey = ["actor_user_name", "src_endpoint_ip", "device_hostname"].find(
    (k) => typeof record[k] === "string" && record[k] !== "" && ENTITY_COLUMNS[k],
  );
  const focus: InvestigateSeed | null = focusKey
    ? {
        kind: ENTITY_COLUMNS[focusKey] as InvestigateSeed["kind"],
        value: String(record[focusKey]),
      }
    : null;
  const srcIp = typeof record.src_endpoint_ip === "string" ? record.src_endpoint_ip : "";
  const when = typeof record.time === "string" ? record.time : null;
  const nobody = !record.actor_user_name;

  return (
    <div className="border-b border-border bg-surface-expand py-3.5 pl-12 pr-3.5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-md">
          {typeof record.message === "string" && record.message
            ? truncate(record.message, 90)
            : eventId
              ? "Event"
              : "Row"}
        </span>
        {record.source_id ? (
          <span className="rounded-badge bg-sev-info-bg px-2 py-px text-xs font-normal text-text-secondary">
            {String(record.source_id)}
          </span>
        ) : null}
        {record.classification ? (
          <span
            className={`rounded-badge px-2 py-px text-xs font-normal ${local ? "bg-local-bg text-local-text" : "bg-cloud-bg text-cloud-text"}`}
          >
            {local ? "Local only" : "Cloud allowed"}
          </span>
        ) : null}
        <span className="ml-auto flex flex-wrap gap-2">
          {selection && eventId ? (
            <button
              type="button"
              aria-pressed={selection.selected}
              onClick={selection.toggle}
              className={`h-7 rounded border px-3 ${selection.selected ? "border-accent bg-accent-subtle text-accent-text" : "border-border-strong text-text hover:bg-surface-head"}`}
            >
              {selection.selected ? "Selected" : "Select"}
            </button>
          ) : null}
          {focus ? (
            <button
              type="button"
              title={`Investigate ${focus.value}`}
              onClick={() => {
                openEntity(focus);
              }}
              className="h-7 rounded border border-border-strong px-3 text-text hover:bg-surface-head"
            >
              Investigate
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => void navigator.clipboard?.writeText(JSON.stringify(record, null, 2))}
            className="h-7 rounded border border-border-strong px-3 text-text hover:bg-surface-head"
          >
            Copy as JSON
          </button>
        </span>
      </div>
      {full.isLoading ? (
        <div className="mb-2 text-sm text-text-muted">Loading full event…</div>
      ) : null}
      {srcIp && nobody && eventId ? <AddressHolders ip={srcIp} at={when} /> : null}
      <div className="flex flex-wrap gap-5">
        <dl className="m-0 grid min-w-0 flex-[1_1_420px] grid-cols-[150px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
          {fields.map((k) => (
            <div key={k} className="group contents">
              <dt className="text-text-secondary">{k}</dt>
              <dd className="m-0 min-w-0">
                <div className="flex min-w-0 items-start gap-2">
                  <span className="min-w-0 flex-1 break-all font-mono">
                    {kindForColumn(k) ? (
                      <EntityLink
                        kind={kindForColumn(k) as EntityKind}
                        value={record[k]}
                        label={formatCell(record[k] ?? null)}
                      />
                    ) : (
                      formatCell(record[k] ?? null)
                    )}
                  </span>
                  {actions?.fields.has(k) && isScalar(record[k]) ? (
                    <span className="flex shrink-0 gap-1 opacity-60 focus-within:opacity-100 group-hover:opacity-100">
                      <FieldButton
                        label="+"
                        title={`Filter for ${k}`}
                        onClick={() => actions.filter(k, String(record[k]), false)}
                      />
                      <FieldButton
                        label="−"
                        title={`Filter out ${k}`}
                        onClick={() => actions.filter(k, String(record[k]), true)}
                      />
                      <FieldButton
                        label="Top"
                        title={`Top values of ${k}`}
                        onClick={() => actions.top(k)}
                      />
                    </span>
                  ) : null}
                </div>
                {placeOf(record[k]) ? (
                  <div className="text-xs text-text-muted">
                    {geoLong(placeOf(record[k]) as GeoInfo)}
                  </div>
                ) : null}
                {(hitsOf(record[k]) ?? []).map((h) => (
                  <div key={`${h.feed}:${h.threat}`} className="flex items-center gap-1.5 text-xs">
                    <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-danger" />
                    <span className="text-text-secondary">{intelLine(h)}</span>
                  </div>
                ))}
              </dd>
            </div>
          ))}
        </dl>
        {typeof raw === "string" ? (
          <div className="min-w-0 flex-[1_1_380px]">
            <div className="mb-1 text-sm text-text-secondary">Raw event</div>
            <pre className="m-0 whitespace-pre-wrap break-all rounded border border-border bg-inset px-3 py-2.5 font-mono text-sm">
              {raw}
            </pre>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function isScalar(v: Cell | undefined): boolean {
  return typeof v === "string" || typeof v === "number" || typeof v === "boolean";
}

function truncate(text: string, n: number): string {
  return text.length > n ? `${text.slice(0, n - 1)}…` : text;
}
