import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Command, PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api, type EntityRisk, type GraphCard, type GraphKind } from "@/lib/api";
import { navigate, useSection } from "@/lib/route";
import { entitySection, parseEntity } from "@/lib/entity";
import { rangeStart, TIME_RANGES, type TimeRangeId } from "@/lib/search";
import { seedSearch } from "@/lib/searchSeed";
import { CardDetail } from "./CardDetail";
import { LaneGraph } from "./LaneGraph";
import { EntitySummary } from "./EntitySummary";
import { PersonTimeline } from "./PersonTimeline";
import { PersonAlerts, PersonSessions, PersonSignIns } from "./PersonLists";
import { RiskTable } from "./RiskTable";
import { kindOf, PLACEHOLDER, rememberedKind, rememberKind, type EntityKind } from "./entityKind";

type Mode = "entity" | "ai";
interface Focus {
  kind: GraphKind;
  value: string;
}

const KIND_LABEL: Record<EntityKind, string> = { user: "User", ip: "IP address", host: "Host" };

/** Investigations (ADR-0016 rows 4 and 5): risky entities, and lanes showing how one
 * entity, or the organization's AI use, connects to everything it touched. */
type PersonTab = "summary" | "timeline" | "sessions" | "sign-ins" | "alerts";
/** A person's tabs (ADR-0038 row 27). */
const PERSON_TABS: [PersonTab, string][] = [
  ["summary", "Summary"],
  ["timeline", "Timeline"],
  ["sessions", "Sessions"],
  ["sign-ins", "Sign-ins"],
  ["alerts", "Alerts"],
];

export function InvestigatePage() {
  const [range, setRange] = useState<TimeRangeId>("7d");
  // The entity lives in the address (`#ip=203.0.113.9`), so every pivot link, Back, and a
  // shared link open the same page (product pass step 2). A service opens the AI flow.
  const linked = parseEntity(useSection());
  const [modeChoice, setMode] = useState<Mode>("entity");
  const mode: Mode = linked?.kind === "service" ? "ai" : modeChoice;
  const entity: Focus | null = linked && linked.kind !== "service" ? linked : null;
  const [aiChoice, setAiFocus] = useState<Focus | null>(null);
  const aiFocus: Focus | null =
    linked?.kind === "service" ? { kind: "service", value: linked.value } : aiChoice;
  const [selected, setSelected] = useState<GraphCard | null>(null);
  const [kind, setKind] = useState<EntityKind>(
    (linked && linked.kind !== "service" ? linked.kind : null) ?? rememberedKind(),
  );
  // The type follows what is typed (F56) until the user picks one from the list.
  const [picked, setPicked] = useState(false);
  const [text, setText] = useState(linked && linked.kind !== "service" ? linked.value : "");
  const [riskTab, setRiskTab] = useState<EntityKind>("user");
  const [personTab, setPersonTab] = useState<PersonTab>("summary");
  // A pivot link from another page while this one is open: the box follows the address.
  const linkedKey = linked && linked.kind !== "service" ? `${linked.kind}=${linked.value}` : "";
  useEffect(() => {
    if (!linked || linked.kind === "service") return;
    setKind(linked.kind);
    setText(linked.value);
    // Only when the linked entity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkedKey]);
  const start = rangeStart(range);
  const rangeLabel = TIME_RANGES.find((r) => r.id === range)?.label ?? "this range";
  const rangeWords = /^last /i.test(rangeLabel) ? `the ${rangeLabel.toLowerCase()}` : rangeLabel;

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
    setMode("entity");
    setPersonTab("summary");
    setKind(next.kind as EntityKind);
    setText(next.value);
    navigate("investigate", entitySection({ kind: next.kind as EntityKind, value: next.value }));
  };
  const pick = (row: EntityRisk) => investigate({ kind: row.kind, value: row.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    rememberKind(kind);
    investigate({ kind, value: text.trim() });
  };
  const openSearch = (sql: string) => {
    seedSearch({ sql, range });
    navigate("search");
  };

  const focusAi = (f: Focus) => {
    setSelected(null);
    setMode("ai");
    setAiFocus(f);
    if (linked) navigate("investigate"); // leave a linked service for this person or server
  };

  // What "Investigate this" does for the selected card, if anything.
  const follow = (card: GraphCard): (() => void) | null => {
    const key = card.id.slice(card.id.indexOf(":") + 1);
    if (mode === "entity" && card.lane === 3)
      return () =>
        investigate({ kind: kindOf(card.label) === "ip" ? "ip" : "host", value: card.label });
    if (mode === "ai" && card.lane === 0) return () => focusAi({ kind: "user", value: card.label });
    if (mode === "ai" && card.lane === 2) return () => focusAi({ kind: "mcp", value: card.label });
    if (mode === "ai" && card.lane === 3 && key.startsWith("svc:"))
      return () => {
        setSelected(null);
        navigate("investigate", entitySection({ kind: "service", value: key.slice(4) }));
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
        onChange={(e) => {
          setKind(e.target.value as EntityKind);
          setPicked(true);
        }}
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
        onChange={(e) => {
          const value = e.target.value;
          setText(value);
          const guess = kindOf(value);
          if (!value.trim()) setPicked(false);
          else if (!picked && guess) setKind(guess);
        }}
        placeholder={PLACEHOLDER[kind]}
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
                  if (linked && (m === "entity") !== (linked.kind !== "service"))
                    navigate("investigate");
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
                    setText("");
                    navigate("investigate");
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
                    setMode("ai");
                    if (linked) navigate("investigate");
                  }}
                  className="text-accent-text hover:underline"
                >
                  Show everyone
                </button>
              </div>
            ) : null}
            {mode === "entity" && entity?.kind === "user" ? (
              <div role="tablist" aria-label="Person" className="flex border-b border-border">
                {PERSON_TABS.map(([t, label]) => (
                  <button
                    key={t}
                    type="button"
                    role="tab"
                    aria-selected={personTab === t}
                    onClick={() => setPersonTab(t)}
                    className={`-mb-px border-b-2 px-3 py-2 text-sm ${
                      personTab === t
                        ? "border-accent font-semibold text-text"
                        : "border-transparent text-text-secondary hover:text-text"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            ) : null}
            {mode === "entity" && entity?.kind === "user" && personTab === "timeline" ? (
              <PersonTimeline person={entity.value} />
            ) : null}
            {mode === "entity" && entity?.kind === "user" && personTab === "sessions" ? (
              <PersonSessions person={entity.value} />
            ) : null}
            {mode === "entity" && entity?.kind === "user" && personTab === "sign-ins" ? (
              <PersonSignIns person={entity.value} />
            ) : null}
            {mode === "entity" && entity?.kind === "user" && personTab === "alerts" ? (
              <PersonAlerts person={entity.value} />
            ) : null}
            {mode === "entity" && entity && !(entity.kind === "user" && personTab !== "summary") ? (
              <EntitySummary
                kind={entity.kind as "user" | "ip" | "host"}
                value={entity.value}
                start={start}
                range={range}
                rangeWords={rangeWords}
                onSearch={openSearch}
              />
            ) : null}
            {mode === "entity" &&
            entity?.kind === "user" &&
            personTab !== "summary" ? null : mode === "entity" && entity ? (
              // The summary answers first; the lanes sit below it and fold away (owner critique).
              <details open className="group rounded-card border border-border bg-surface">
                <summary className="cursor-pointer px-3 py-2 text-sm font-semibold">
                  How it connects{" "}
                  <span className="font-normal text-text-muted">
                    sources, activities, and targets as lanes
                  </span>
                </summary>
                <section
                  aria-label="Investigation graph"
                  className="overflow-hidden border-t border-border bg-inset"
                >
                  {canvas}
                </section>
              </details>
            ) : (
              <section
                aria-label="Investigation graph"
                className="overflow-hidden rounded-card border border-border bg-inset"
              >
                {canvas}
              </section>
            )}
            {g &&
            !selected &&
            !(entity?.kind === "user" && personTab !== "summary") &&
            g.cards.length > (mode === "entity" ? 1 : 0) ? (
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
