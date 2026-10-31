import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { EntityLink } from "@/components/EntityLink";
import { LoadFailed } from "@/components/LoadFailed";
import { api, type InventoryItem, type InventoryType } from "@/lib/api";
import { cn } from "@/lib/cn";
import { since, stamp } from "@/features/overview/time";
import { STATUS_LABEL, StatusBadge } from "./StatusBadge";

const TYPE_LABEL: Record<InventoryType, string> = {
  service: "AI services",
  agent: "Agents",
  mcp: "MCP servers",
  m365_app: "Microsoft 365 apps",
};
const ONE: Record<InventoryType, string> = {
  service: "AI service",
  agent: "Agent",
  mcp: "MCP server",
  m365_app: "Microsoft 365 app",
};
const TYPES = Object.keys(TYPE_LABEL) as InventoryType[];
type Group = "none" | "type" | "status";
const TH = "px-3 py-2 font-semibold";
const TD = "px-3 py-1.5";

function save(text: string, name: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function statusText(i: InventoryItem): string {
  return i.status ? STATUS_LABEL[i.status] : "No review";
}

/** AI usage > Inventory (ADR-0038 section 7): everything AI seen in one typed list, by
 * type, Active or Excluded, grouped as asked; the view exports as CSV or JSON, audited. */
export function InventoryCard({ isAdmin, canExport }: { isAdmin: boolean; canExport: boolean }) {
  const client = useQueryClient();
  const q = useQuery({ queryKey: ["ai-inventory"], queryFn: () => api.aiInventory(30) });
  const [type, setType] = useState<InventoryType | null>(null);
  const [excludedView, setExcludedView] = useState(false);
  const [group, setGroup] = useState<Group>("none");
  const [excluding, setExcluding] = useState<InventoryItem | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const refresh = () => void client.invalidateQueries({ queryKey: ["ai-inventory"] });
  const include = useMutation({
    mutationFn: (i: InventoryItem) => api.includeInventory(i.type, i.key),
    onSuccess: refresh,
  });
  const items = q.data?.items ?? [];
  const inView = items.filter((i) => (i.excluded !== null) === excludedView);
  const rows = inView.filter((i) => type === null || i.type === type);
  const count = (t: InventoryType | null) =>
    inView.filter((i) => t === null || i.type === t).length;
  const groups: [string, InventoryItem[]][] =
    group === "none"
      ? [["", rows]]
      : [
          ...rows
            .reduce((m, i) => {
              const k = group === "type" ? ONE[i.type] : statusText(i);
              m.set(k, [...(m.get(k) ?? []), i]);
              return m;
            }, new Map<string, InventoryItem[]>())
            .entries(),
        ];
  const doExport = async (format: "csv" | "json") => {
    setExportError(null);
    try {
      const text = await api.aiInventoryExport(format, { days: 30, type, excluded: excludedView });
      save(text, `ai-inventory.${format}`, format === "csv" ? "text/csv" : "application/json");
    } catch (e) {
      setExportError(e instanceof Error ? e.message : "The export failed");
    }
  };
  const now = new Date().toISOString();
  return (
    <section
      aria-label="AI inventory"
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border bg-surface-head px-3 py-2">
        <h2 className="text-base font-semibold">Inventory</h2>
        <span className="text-sm text-text-muted">
          Everything AI seen in the last 30 days, from the sources you can read.
        </span>
        <span className="ml-auto flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-sm">
            <span className="text-text-secondary">Group by</span>
            <select
              value={group}
              onChange={(e) => setGroup(e.target.value as Group)}
              className="h-8 rounded border border-border bg-surface px-2 text-sm"
            >
              <option value="none">None</option>
              <option value="type">Type</option>
              <option value="status">Status</option>
            </select>
          </label>
          {canExport ? (
            <>
              <button
                type="button"
                onClick={() => void doExport("csv")}
                className="h-8 rounded border border-border px-3 text-sm hover:bg-surface"
              >
                Export CSV
              </button>
              <button
                type="button"
                onClick={() => void doExport("json")}
                className="h-8 rounded border border-border px-3 text-sm hover:bg-surface"
              >
                Export JSON
              </button>
            </>
          ) : null}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-3 py-2">
        <div role="group" aria-label="Type" className="flex flex-wrap gap-1">
          {[null, ...TYPES].map((t) => (
            <button
              key={t ?? "all"}
              type="button"
              aria-pressed={type === t}
              onClick={() => setType(t)}
              className={cn(
                "h-7 rounded px-2 text-sm",
                type === t
                  ? "bg-surface-head font-semibold text-text"
                  : "text-text-secondary hover:text-text",
              )}
            >
              {t ? TYPE_LABEL[t] : "All"}{" "}
              <span className="font-mono tabular-nums text-text-muted">{count(t)}</span>
            </button>
          ))}
        </div>
        <div role="group" aria-label="State" className="ml-auto flex rounded border border-border">
          {[false, true].map((x) => (
            <button
              key={String(x)}
              type="button"
              aria-pressed={excludedView === x}
              onClick={() => setExcludedView(x)}
              className={cn(
                "h-7 px-3 text-sm first:rounded-l last:rounded-r",
                excludedView === x
                  ? "bg-surface-head font-semibold text-text"
                  : "text-text-secondary hover:text-text",
              )}
            >
              {x ? "Excluded" : "Active"}{" "}
              <span className="font-mono tabular-nums text-text-muted">
                {items.filter((i) => (i.excluded !== null) === x).length}
              </span>
            </button>
          ))}
        </div>
      </div>
      {exportError ? (
        <p role="alert" className="border-b border-border px-3 py-2 text-sm text-warn">
          {exportError}
        </p>
      ) : null}
      {excluding ? (
        <ExcludeForm
          item={excluding}
          onDone={() => {
            setExcluding(null);
            refresh();
          }}
          onCancel={() => setExcluding(null)}
        />
      ) : null}
      {q.isLoading ? (
        <div aria-busy="true" className="h-40 animate-pulse" />
      ) : q.isError ? (
        <LoadFailed
          what="the AI inventory"
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
        />
      ) : rows.length === 0 ? (
        <p className="px-3 py-4 text-sm text-text-secondary">
          {excludedView
            ? "Nothing is excluded. Excluded items move here with who excluded them and why."
            : "Nothing AI seen in the last 30 days for this type."}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-secondary">
                <th className={TH}>Name</th>
                <th className={TH}>Type</th>
                <th className={TH}>Status</th>
                <th className={`${TH} text-right`}>People</th>
                <th className={`${TH} text-right`}>Devices</th>
                <th className={TH}>First seen</th>
                <th className={TH}>Last seen</th>
                <th className={TH}>Seen in</th>
                {excludedView ? <th className={TH}>Excluded</th> : null}
                {isAdmin ? (
                  <th className={TH}>
                    <span className="sr-only">Actions</span>
                  </th>
                ) : null}
              </tr>
            </thead>
            {groups.map(([label, list]) => (
              <tbody key={label || "all"}>
                {label ? (
                  <tr className="border-b border-border bg-surface-head">
                    <th colSpan={10} className="px-3 py-1.5 text-left text-sm font-semibold">
                      {label}{" "}
                      <span className="font-mono font-normal tabular-nums text-text-muted">
                        {list.length}
                      </span>
                    </th>
                  </tr>
                ) : null}
                {list.map((i) => (
                  <tr
                    key={`${i.type}:${i.key}`}
                    data-row={i.key}
                    className="border-b border-border last:border-0"
                  >
                    <td className={`${TD} font-mono`}>{i.name}</td>
                    <td className={`${TD} text-text-secondary`}>{ONE[i.type]}</td>
                    <td className={TD}>
                      {i.status ? (
                        <StatusBadge status={i.status} />
                      ) : (
                        <span className="text-text-muted">No review</span>
                      )}
                    </td>
                    <td className={`${TD} text-right font-mono tabular-nums`}>{i.people}</td>
                    <td className={`${TD} text-right font-mono tabular-nums`}>
                      {i.devices ?? "·"}
                    </td>
                    <When at={i.first_seen} now={now} />
                    <When at={i.last_seen} now={now} />
                    <td className={`${TD} text-text-secondary`}>{i.where.join(", ")}</td>
                    {excludedView ? (
                      <td className={TD}>
                        {i.excluded ? (
                          <span title={`${stamp(i.excluded.at)} UTC`}>
                            <EntityLink kind="user" value={i.excluded.by} />
                            <span className="text-text-secondary">: {i.excluded.reason}</span>
                          </span>
                        ) : null}
                      </td>
                    ) : null}
                    {isAdmin ? (
                      <td className={`${TD} text-right`}>
                        {i.excluded ? (
                          <button
                            type="button"
                            onClick={() => include.mutate(i)}
                            className="text-accent-text hover:underline"
                            aria-label={`Move ${i.name} back to Active`}
                          >
                            Move to Active
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setExcluding(i)}
                            className="text-accent-text hover:underline"
                            aria-label={`Exclude ${i.name}`}
                          >
                            Exclude
                          </button>
                        )}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      )}
    </section>
  );
}

function When({ at, now }: { at: string | null; now: string }) {
  return (
    <td className={`${TD} whitespace-nowrap`} title={at ? `${stamp(at)} UTC` : undefined}>
      {at ? since(at, now) : ""}
    </td>
  );
}

function ExcludeForm({
  item,
  onDone,
  onCancel,
}: {
  item: InventoryItem;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => api.excludeInventory(item.type, item.key, reason.trim()),
    onSuccess: onDone,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (reason.trim()) m.mutate();
  };
  return (
    <form
      onSubmit={submit}
      aria-label={`Exclude ${item.name}`}
      className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2 text-sm"
    >
      <span>
        Exclude <span className="font-mono">{item.name}</span> from the Active list. It still shows
        in Search, alerts, and AI Watch.
      </span>
      <input
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        maxLength={500}
        placeholder="Why (required)"
        aria-label="Reason"
        className="h-8 min-w-0 flex-1 rounded border border-border bg-surface px-2"
      />
      <button
        type="submit"
        disabled={!reason.trim() || m.isPending}
        className="h-8 rounded bg-accent px-3 font-semibold text-white disabled:opacity-50"
      >
        Exclude
      </button>
      <button type="button" onClick={onCancel} className="h-8 px-2 text-text-secondary">
        Cancel
      </button>
      {m.isError ? <span className="text-warn">{(m.error as Error).message}</span> : null}
    </form>
  );
}
