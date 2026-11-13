import { Skeleton } from "@/components/Skeleton";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api, type EntityRisk, type GraphCard, type GraphKind } from "@/lib/api";
import { navigate, useSection } from "@/lib/route";
import { entitySection, parseEntity, parseEntityTab } from "@/lib/entity";
import { FilterBar } from "@/components/FilterBar";
import { usePageTimeState } from "@/lib/timeChoice";
import type { TimeChoice } from "@/lib/timeWindow";
import { seedSearch } from "@/lib/searchSeed";
import { CardDetail } from "./CardDetail";
import { LaneGraph } from "./LaneGraph";
import { EntitySummary } from "./EntitySummary";
import { PersonTimeline } from "./PersonTimeline";
import { PersonAiActivity } from "./PersonAiActivity";
import { PersonAlerts, PersonSignIns } from "./PersonLists";
import { PersonHosts } from "./PersonHosts";
import { RiskTable } from "./RiskTable";
import { TargetedTable } from "./TargetedTable";
import { kindOf, type EntityKind } from "./entityKind";
import { SectionTitle } from "@/components/SectionTitle";

type Mode = "entity" | "ai";
interface Focus {
  kind: GraphKind;
  value: string;
}

const KIND_LABEL: Record<EntityKind, string> = { user: "User", ip: "IP address", host: "Host" };
/** The landing tabs: the three kinds, then usernames only ever tried from outside (D212). */
type RiskTab = EntityKind | "targeted";
const RISK_TABS: [RiskTab, string][] = [
  ["user", "Users"],
  ["ip", "IP addresses"],
  ["host", "Hosts"],
  ["targeted", "Targeted usernames"],
];

/** Investigations (ADR-0016 rows 4 and 5): risky entities, and lanes showing how one
 * entity, or the organization's AI use, connects to everything it touched. */
type PersonTab = "summary" | "ai" | "hosts" | "alerts" | "timeline";
/** A person's page, one per person (ADR-0038 row 27, D197): identity and Microsoft 365
 * (the summary, lanes, and sign-ins), AI use, hosts and devices, alerts, and the timeline.
 * AI usage, Agents, and People and devices all open this page. */
const PERSON_TABS: [PersonTab, string][] = [
  ["summary", "Identity and M365"],
  ["ai", "AI use"],
  ["hosts", "Hosts and devices"],
  ["alerts", "Alerts"],
  ["timeline", "Timeline"],
];

/** The page's range in days for the panels that count whole days back from now (1 to 30).
 * Custom counts from its start, or 30 days when the start is open. */
function rangeDays(choice: TimeChoice, start: string | undefined): number {
  if (choice.preset === "custom") {
    if (!start) return 30;
    const days = Math.ceil((Date.now() - Date.parse(start)) / 86_400_000);
    return Math.min(30, Math.max(1, days));
  }
  return choice.preset === "24h" || choice.preset === "1h" ? 1 : choice.preset === "30d" ? 30 : 7;
}

export function InvestigatePage() {
  // Kept in the page, not the address: the fragment names what is open and every pivot
  // rewrites it.
  const time = usePageTimeState("7d");
  const range = time.key.join("|");
  // The entity lives in the address (`#ip=203.0.113.9`), so every pivot link, Back, and a
  // shared link open the same page (product pass step 2). A service opens the AI flow.
  const section = useSection();
  const linked = parseEntity(section);
  const linkedTab = parseEntityTab(section);
  const [modeChoice, setMode] = useState<Mode>("entity");
  const mode: Mode = linked?.kind === "service" ? "ai" : modeChoice;
  const entity: Focus | null = linked && linked.kind !== "service" ? linked : null;
  const [aiChoice, setAiFocus] = useState<Focus | null>(null);
  const aiFocus: Focus | null =
    linked?.kind === "service" ? { kind: "service", value: linked.value } : aiChoice;
  const [selected, setSelected] = useState<GraphCard | null>(null);
  const [riskTab, setRiskTab] = useState<RiskTab>("user");
  const [personTab, setPersonTab] = useState<PersonTab>(linkedTab ?? "summary");
  // A link that names a tab opens it (AI usage and Agents open AI activity).
  const [seenSection, setSeenSection] = useState(section);
  if (section !== seenSection) {
    setSeenSection(section);
    if (linkedTab) setPersonTab(linkedTab);
  }
  const { start, end } = time.bounds();
  const rangeWords = time.words;

  const risk = useQuery({
    queryKey: ["entity-risk", range],
    queryFn: () => api.entityRisk(start, end),
    staleTime: 60_000,
  });
  const focus = mode === "entity" ? entity : aiFocus;
  const graph = useQuery({
    queryKey: ["entity-graph", mode, focus?.kind, focus?.value, range],
    queryFn: () => api.entityGraph({ mode, kind: focus?.kind, value: focus?.value, start, end }),
    enabled: mode === "ai" || entity !== null,
    staleTime: 60_000,
  });

  const investigate = (next: Focus) => {
    setSelected(null);
    setMode("entity");
    setPersonTab("summary");
    navigate("investigate", entitySection({ kind: next.kind as EntityKind, value: next.value }));
  };
  const pick = (row: EntityRisk) => investigate({ kind: row.kind, value: row.value });
  const openSearch = (sql: string) => {
    seedSearch(
      time.choice.preset === "custom"
        ? { sql, custom: { from: time.choice.from, to: time.choice.to } }
        : { sql, range: time.choice.preset },
    );
    navigate("logs");
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
    // D242: a masked card is a machine, never a person to follow.
    if (mode === "ai" && card.lane === 0)
      return graph.data?.masked ? null : () => focusAi({ kind: "user", value: card.label });
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
  const targeted = risk.data?.targeted ?? [];
  const counts: Record<RiskTab, number> = {
    user: lists.user.length,
    ip: lists.ip.length,
    host: lists.host.length,
    targeted: risk.data?.targeted_total ?? targeted.length,
  };
  const empty =
    risk.data &&
    !risk.data.users.length &&
    !risk.data.ips.length &&
    !risk.data.hosts.length &&
    !targeted.length;
  const g = graph.data;
  const followFn = selected ? follow(selected) : null;

  const kindTabs = RISK_TABS.map(([k, name]) => (
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
      {/* A count only once it is known: never "(0)" while the page is still loading. */}
      {risk.data ? `${name} (${counts[k].toLocaleString()})` : name}
    </button>
  ));

  const canvas = graph.error ? (
    <p role="alert" className="p-4 text-sm text-danger">
      {graph.error instanceof ApiError ? graph.error.message : "Could not load the graph"}
    </p>
  ) : graph.isLoading ? (
    <Skeleton label="the graph" rows={4} className="rounded-none border-0" />
  ) : g && g.cards.length <= (mode === "entity" ? 1 : 0) ? (
    <p className="p-6 text-sm text-text-secondary">
      {mode === "entity"
        ? `No events for ${entity?.value ?? "this entity"} in this range, in the sources you may read.`
        : "No AI activity in this range, in the sources you may read. Claude Code telemetry, the MCP inventory, and DNS or firewall logs feed this view."}
    </p>
  ) : g ? (
    <div className="flex flex-col">
      {g.masked ? (
        // D242: the server sent machines in place of names.
        <p className="px-3 py-2 text-sm text-text-muted">
          Names are hidden. An admin can turn on View people in AI usage for you.
        </p>
      ) : null}
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
    </div>
  ) : null;

  const landing = mode === "entity" && !entity;

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        title="People &amp; devices"
        count={
          risk.data
            ? `${risk.data.matches_considered.toLocaleString()} rule matches considered`
            : null
        }
      />
      <div className="flex flex-col gap-4 px-5 py-3">
        <FilterBar
          label="Filter people and devices by time"
          time={time.bar}
          onReset={() => time.bar.onChange("7d")}
          isDefault={time.isDefault}
        />

        {landing ? (
          <>
            <section
              aria-label="Most active entities"
              className="mx-auto w-full max-w-5xl rounded-card border border-border bg-surface"
            >
              <div className="flex flex-wrap items-end justify-between gap-2 border-b border-border px-4 pt-3">
                <div className="pb-2">
                  <SectionTitle>Most active</SectionTitle>
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
                <div role="status" aria-busy="true" className="flex flex-col gap-2 p-4">
                  <p className="text-sm text-text-secondary">
                    Counting people and devices for {rangeWords}. A long range over busy sources can
                    take a while.
                  </p>
                  <div className="h-1 w-full overflow-hidden rounded bg-surface-head">
                    <div className="h-1 w-1/3 animate-pulse rounded bg-accent" />
                  </div>
                </div>
              ) : empty ? (
                <p className="p-4 text-sm text-text-secondary">
                  No users, IP addresses, or hosts in this range, in the sources you can read. Pick
                  a longer range, or open any of them from the search in the top bar.
                </p>
              ) : riskTab === "targeted" ? (
                targeted.length === 0 ? (
                  <p className="p-4 text-sm text-text-muted">
                    No usernames were only ever tried in failed sign-ins in this range.
                  </p>
                ) : (
                  <TargetedTable
                    rows={targeted}
                    onPick={(t) => investigate({ kind: "user", value: t.value })}
                  />
                )
              ) : lists[riskTab].length === 0 ? (
                <p className="p-4 text-sm text-text-muted">Nothing ranked for this type.</p>
              ) : (
                <RiskTable
                  kind={riskTab}
                  label={riskTab === "user" ? "User" : riskTab === "ip" ? "Source IP" : "Host"}
                  rows={lists[riskTab]}
                  onPick={pick}
                  start={start}
                  end={end}
                  aiPeopleHidden={risk.data?.ai_people_hidden}
                />
              )}
              {/* Access is said on the page; how the score adds up is on the Score column. */}
              <p className="border-t border-border px-4 py-2 text-xs text-text-muted">
                Only sources you may read are counted.
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
            {mode === "entity" && entity?.kind === "user" && personTab === "ai" ? (
              <PersonAiActivity person={entity.value} days={rangeDays(time.choice, start)} />
            ) : null}
            {mode === "entity" && entity?.kind === "user" && personTab === "timeline" ? (
              <PersonTimeline person={entity.value} />
            ) : null}
            {mode === "entity" && entity?.kind === "user" && personTab === "hosts" ? (
              <PersonHosts person={entity.value} days={rangeDays(time.choice, start)} />
            ) : null}
            {mode === "entity" && entity?.kind === "user" && personTab === "alerts" ? (
              <PersonAlerts person={entity.value} />
            ) : null}
            {mode === "entity" && entity && !(entity.kind === "user" && personTab !== "summary") ? (
              <EntitySummary
                kind={entity.kind as "user" | "ip" | "host"}
                value={entity.value}
                start={start}
                end={end}
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
            {mode === "entity" && entity?.kind === "user" && personTab === "summary" ? (
              <PersonSignIns person={entity.value} />
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
