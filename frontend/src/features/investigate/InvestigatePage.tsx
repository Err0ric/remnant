import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Command, PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api, type EntityRisk, type GraphCard, type GraphKind } from "@/lib/api";
import { navigate } from "@/lib/route";
import { rangeStart, TIME_RANGES, type TimeRangeId } from "@/lib/search";
import { seedSearch } from "@/lib/searchSeed";
import { takeInvestigateSeed } from "@/lib/investigateSeed";
import { CardDetail } from "./CardDetail";
import { LaneGraph } from "./LaneGraph";
import { RiskTable } from "./RiskTable";

type Mode = "entity" | "ai";
type EntityKind = "user" | "ip" | "host";
interface Focus {
  kind: GraphKind;
  value: string;
}

const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;
const KIND_LABEL: Record<EntityKind, string> = { user: "User", ip: "IP address", host: "Host" };

/** Investigations (ADR-0016 rows 4 and 5): risky entities, and lanes showing how one
 * entity, or the organization's AI use, connects to everything it touched. */
export function InvestigatePage() {
  // "Investigate" on a field in Search opens the page on that entity.
  const [handoff] = useState(takeInvestigateSeed);
  const [range, setRange] = useState<TimeRangeId>("7d");
  const [mode, setMode] = useState<Mode>("entity");
  const [entity, setEntity] = useState<Focus | null>(handoff);
  const [aiFocus, setAiFocus] = useState<Focus | null>(null);
  const [selected, setSelected] = useState<GraphCard | null>(null);
  const [kind, setKind] = useState<EntityKind>(handoff?.kind ?? "user");
  const [text, setText] = useState(handoff?.value ?? "");
  const [riskTab, setRiskTab] = useState<EntityKind>("user");
  const start = rangeStart(range);

  const risk = useQuery({
    queryKey: ["entity-risk", range],
    queryFn: () => api.entityRisk(start),
    staleTime: 60_000,
  });
  const focus = mode === "entity" ? entity : aiFocus;
  const graph = useQuery({
    queryKey: ["entity-graph", mode, focus?.kind, focus?.value, range],
    queryFn: () => api.entityGraph({ mode, kind: focus?.kind, value: focus?.value, start }),
    enabled: mode === "ai" || entity !== null,
    staleTime: 60_000,
  });

  const investigate = (next: Focus) => {
    setSelected(null);
    setEntity(next);
    setMode("entity");
    setKind(next.kind as EntityKind);
    setText(next.value);
  };
  const pick = (row: EntityRisk) => investigate({ kind: row.kind, value: row.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) investigate({ kind, value: text.trim() });
  };
  const openSearch = (sql: string) => {
    seedSearch({ sql, range });
    navigate("search");
  };

  // What "Investigate this" does for the selected card, if anything.
  const follow = (card: GraphCard): (() => void) | null => {
    const key = card.id.slice(card.id.indexOf(":") + 1);
    if (mode === "entity" && card.lane === 3)
      return () => investigate({ kind: IPV4.test(card.label) ? "ip" : "host", value: card.label });
    if (mode === "ai" && card.lane === 0)
      return () => {
        setSelected(null);
        setAiFocus({ kind: "user", value: card.label });
      };
    if (mode === "ai" && card.lane === 2)
      return () => {
        setSelected(null);
        setAiFocus({ kind: "mcp", value: card.label });
      };
    if (mode === "ai" && card.lane === 3 && key.startsWith("svc:"))
      return () => {
        setSelected(null);
        setAiFocus({ kind: "service", value: key.slice(4) });
      };
    return null;
  };

  const lists = risk.data
    ? { user: risk.data.users, ip: risk.data.ips, host: risk.data.hosts }
    : { user: [], ip: [], host: [] };
  const empty = risk.data && risk.data.matches_considered === 0;
  const g = graph.data;
  const followFn = selected ? follow(selected) : null;

  const kindTabs = (Object.keys(KIND_LABEL) as EntityKind[]).map((k) => (
    <button
      key={k}
      type="button"
      role="tab"
      aria-selected={riskTab === k}
      onClick={() => setRiskTab(k)}
      className={`-mb-px border-b-2 px-3 py-2 text-sm ${
        riskTab === k
          ? "border-accent font-semibold text-text"
          : "border-transparent text-text-secondary hover:text-text"
      }`}
    >
      {k === "user" ? "Users" : k === "ip" ? "IP addresses" : "Hosts"} ({lists[k].length})
    </button>
  ));

  const picker = (
    <form
      onSubmit={submit}
      aria-label="Investigate an entity"
      className="flex flex-wrap items-center gap-2"
    >
      <select
        aria-label="Entity type"
        value={kind}
        onChange={(e) => setKind(e.target.value as EntityKind)}
        className="h-9 rounded border border-border-strong bg-inset px-2 text-sm"
      >
        {(Object.keys(KIND_LABEL) as EntityKind[]).map((k) => (
          <option key={k} value={k}>
            {KIND_LABEL[k]}
          </option>
        ))}
      </select>
      <input
        aria-label="Entity"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="alice@example.com, 203.0.113.9, ws-0042"
        className="h-9 min-w-0 flex-[1_1_16rem] rounded border border-border-strong bg-inset px-3 font-mono text-sm"
      />
      <button
        type="submit"
        disabled={!text.trim()}
        className="h-9 rounded bg-accent px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50"
      >
        Investigate
      </button>
    </form>
  );

  const canvas = graph.error ? (
    <p role="alert" className="p-4 text-sm text-danger">
      {graph.error instanceof ApiError ? graph.error.message : "Could not load the graph"}
    </p>
  ) : graph.isLoading ? (
    <p className="p-4 text-sm text-text-muted">Loading…</p>
  ) : g && g.cards.length <= (mode === "entity" ? 1 : 0) ? (
    <p className="p-6 text-sm text-text-secondary">
      {mode === "entity"
        ? `No events for ${entity?.value ?? "this entity"} in this range, in the sources you may read.`
        : "No AI activity in this range, in the sources you may read. Claude Code telemetry, the MCP inventory, and DNS or firewall logs feed this view."}
    </p>
  ) : g ? (
    <div className="flex flex-col lg:flex-row">
      <LaneGraph graph={g} selected={selected?.id ?? null} onSelect={setSelected} />
      {selected ? (
        <CardDetail
          lane={g.lanes[selected.lane] ?? ""}
          card={selected}
          canFollow={followFn !== null}
          onFollow={() => followFn?.()}
          onOpenSearch={openSearch}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </div>
  ) : null;

  const landing = mode === "entity" && !entity;

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        crumbs={["Home", "Investigate", "Investigations"]}
        title="Investigations"
        commands={
          <Command
            label={risk.isFetching || graph.isFetching ? "Refreshing…" : "Refresh"}
            onClick={() => {
              void risk.refetch();
              if (mode === "ai" || entity) void graph.refetch();
            }}
            disabled={risk.isFetching || graph.isFetching}
          />
        }
        meta={
          risk.data
            ? `${risk.data.matches_considered.toLocaleString()} rule matches considered`
            : null
        }
      />
      <div className="flex flex-col gap-4 px-5 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div
            role="radiogroup"
            aria-label="View"
            className="flex rounded border border-border-strong"
          >
            {(["entity", "ai"] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                onClick={() => {
                  setSelected(null);
                  setMode(m);
                }}
                className={`h-8 px-3 text-sm ${
                  mode === m
                    ? "bg-accent-subtle font-semibold text-accent-text"
                    : "hover:bg-surface-head"
                }`}
              >
                {m === "entity" ? "Entity" : "AI flow"}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-sm">
            <span className="text-text-secondary">Time range</span>
            <select
              value={range}
              onChange={(e) => setRange(e.target.value as TimeRangeId)}
              className="h-8 rounded border border-border-strong bg-surface px-2 text-sm"
            >
              {TIME_RANGES.filter((r) => r.id !== "15m").map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {landing ? (
          <>
            <section
              aria-label="Start an investigation"
              className="mx-auto flex w-full max-w-3xl flex-col gap-3 rounded-card border border-border bg-surface p-5"
            >
              <div>
                <h2 className="text-base font-semibold">Investigate activity</h2>
                <p className="text-text-secondary">
                  Pick a user, IP address, or host to see its sources, activities, and targets.
                </p>
              </div>
              {picker}
            </section>

            <section
              aria-label="Most active entities"
              className="mx-auto w-full max-w-5xl rounded-card border border-border bg-surface"
            >
              <div className="flex flex-wrap items-end justify-between gap-2 border-b border-border px-4 pt-3">
                <div className="pb-2">
                  <h2 className="text-base font-semibold">Most active</h2>
                  <p className="text-xs text-text-muted">
                    Ranked by detection rule matches in this range. Select a row to investigate.
                  </p>
                </div>
                <div role="tablist" aria-label="Entity type" className="flex">
                  {kindTabs}
                </div>
              </div>
              {risk.error ? (
                <p role="alert" className="p-4 text-sm text-danger">
                  {risk.error instanceof ApiError ? risk.error.message : "Could not load risk"}
                </p>
              ) : risk.isLoading ? (
                <p className="p-4 text-sm text-text-muted">Loading…</p>
              ) : empty ? (
                <div className="flex flex-col gap-2 p-4 text-sm text-text-secondary">
                  <p>No detection rule has matched in this range, so nothing is ranked yet.</p>
                  <p>
                    Enable rules and run them, or schedule them. You can still investigate any user,
                    IP address, or host above.
                  </p>
                  <button
                    type="button"
                    onClick={() => navigate("rules")}
                    className="self-start text-accent-text hover:underline"
                  >
                    Go to Detection rules
                  </button>
                </div>
              ) : lists[riskTab].length === 0 ? (
                <p className="p-4 text-sm text-text-muted">Nothing ranked for this type.</p>
              ) : (
                <RiskTable
                  label={riskTab === "user" ? "User" : riskTab === "ip" ? "Source IP" : "Host"}
                  rows={lists[riskTab]}
                  onPick={pick}
                />
              )}
              <p className="border-t border-border px-4 py-2 text-xs text-text-muted">
                Score: 10 per critical, 5 per high, 2 per medium, 1 per low rule match, plus 3 per
                flagged schedule run that names it. Only sources you may read are counted.
              </p>
            </section>
          </>
        ) : (
          <>
            {mode === "entity" && entity ? (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <button
                  type="button"
                  onClick={() => {
                    setSelected(null);
                    setEntity(null);
                    setText("");
                  }}
                  className="text-sm text-accent-text hover:underline"
                >
                  ← All entities
                </button>
                <div className="flex min-w-0 items-baseline gap-2">
                  <span className="text-sm text-text-secondary">
                    {KIND_LABEL[entity.kind as EntityKind] ?? "Entity"}
                  </span>
                  <span className="break-all font-mono text-lg">{entity.value}</span>
                </div>
                <div className="ml-auto w-full max-w-xl">{picker}</div>
              </div>
            ) : null}
            {mode === "ai" && aiFocus ? (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-text-secondary">Showing AI flow for</span>
                <span className="font-mono">{aiFocus.value}</span>
                <button
                  type="button"
                  onClick={() => {
                    setSelected(null);
                    setAiFocus(null);
                  }}
                  className="text-accent-text hover:underline"
                >
                  Show everyone
                </button>
              </div>
            ) : null}
            <section
              aria-label="Investigation graph"
              className="overflow-hidden rounded-card border border-border bg-inset"
            >
              {canvas}
            </section>
            {g && !selected && g.cards.length > (mode === "entity" ? 1 : 0) ? (
              <p className="text-sm text-text-muted">
                Select a card to light its path and open its details.
              </p>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
