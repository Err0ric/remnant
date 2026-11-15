import { EmptyState } from "@/components/EmptyState";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AUTO_PARSER } from "@/lib/parsers";
import { ParserEditor } from "./ParserEditor";
import { ParserMix } from "./ParserMix";
import { Fragment, useEffect, useState } from "react";
import { useSection } from "@/lib/route";
import { GapNote } from "@/features/health/GapNote";
import { idleText, quietFrom, shownGaps } from "@/features/health/flow";
import { PageHeader } from "@/components/shell/PageHeader";
import { ApiError, api, type Source, type SourceInput } from "@/lib/api";
import { AddSourceForm } from "./AddSourceForm";
import { DiscoverPanel } from "./DiscoverPanel";
import { ClassificationBadge } from "./ClassificationBadge";
import { ClassificationEditor } from "./ClassificationEditor";
import { ApiSummary } from "./ApiSummary";
import { ListenerSummary } from "./ListenerSummary";
import { LokiSummary } from "./LokiSummary";
import { OtlpControls } from "./OtlpSetup";
import { MappingChanges } from "./MappingChanges";
import { QuietAlert } from "./QuietAlert";
import { QuietOkEditor } from "./QuietOkEditor";
import { VendorAlertNotify } from "./VendorAlertNotify";
import { ReparseControl } from "./ReparseControl";
import { ReparseRulesControl } from "./ReparseRulesControl";
import { SourceState } from "./SourceState";
import { TimeZoneEditor } from "./TimeZoneEditor";
import { RetentionEditor } from "./RetentionEditor";
import { ConnectorSettingsButton } from "./ConnectorSettingsEditor";
import { since } from "@/features/overview/time";
import { SectionTitle } from "@/components/SectionTitle";

interface SourcesPageProps {
  canManage: boolean;
}

/** Path with break opportunities after each slash, so long paths wrap at folder boundaries. */
function WrappedPath({ path }: { path: string }) {
  const parts = path.split("/");
  return (
    <>
      {parts.map((part, i) => (
        <Fragment key={i}>
          {part}
          {i < parts.length - 1 ? (
            <>
              /<wbr />
            </>
          ) : null}
        </Fragment>
      ))}
    </>
  );
}

function formatTime(value: unknown): string {
  if (typeof value !== "string") return "·";
  return `${value.slice(0, 19).replace("T", " ")} UTC`;
}

export function SourcesPage({ canManage }: SourcesPageProps) {
  const client = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  // Bumped on each "Add as source" so the form remounts with the new suggestion.
  const [suggestion, setSuggestion] = useState<{ key: number; values: Partial<SourceInput> }>({
    key: 0,
    values: {},
  });
  const [confirming, setConfirming] = useState<string | null>(null);

  const sources = useQuery({
    queryKey: ["source-list"],
    queryFn: api.sources,
    refetchInterval: 5000,
  });
  // Gaps in the last 24 hours, as Health shows them (F61), and the source a link opened.
  const overview = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const gapsOf = new Map((overview.data?.volume ?? []).map((v) => [v.source_id, v.gaps]));
  const judged = new Map((overview.data?.sources ?? []).map((h) => [h.source_id, h]));
  const section = useSection();
  const focus = section.startsWith("source=") ? decodeURIComponent(section.slice(7)) : null;
  useEffect(() => {
    if (focus) document.getElementById(`source-${focus}`)?.scrollIntoView?.({ block: "center" });
  }, [focus, sources.isSuccess]);
  // Server folder layout is admin-only; analysts never request it.
  const settings = useQuery({
    queryKey: ["source-list", "settings"],
    queryFn: api.sourceSettings,
    enabled: canManage,
  });
  // Counts come from the lake through the normal guarded query path. Not polled, since each
  // query is audited; refreshed on demand.
  const counts = useQuery({
    queryKey: ["source-list", "counts"],
    queryFn: api.sourceEventCounts,
  });
  const templates = useQuery({
    queryKey: ["templates"],
    queryFn: api.templates,
    staleTime: 60_000,
  });
  const list: Source[] = sources.data ?? [];
  const autoIds = list.filter((s) => s.template_id === AUTO_PARSER).map((s) => s.source_id);
  const mix = useQuery({
    queryKey: ["source-list", "mix", autoIds.join(",")],
    queryFn: api.sourceParserMix,
    enabled: autoIds.length > 0,
  });
  const mixFor = new Map<string, Map<string, number>>();
  for (const row of mix.data?.rows ?? []) {
    const sid = String(row[0]);
    const per = mixFor.get(sid) ?? new Map<string, number>();
    per.set(String(row[1]), Number(row[2]));
    mixFor.set(sid, per);
  }
  const remove = useMutation({
    mutationFn: api.deleteSource,
    onSuccess: async () => {
      setConfirming(null);
      await client.invalidateQueries({ queryKey: ["source-list"] });
      await client.invalidateQueries({ queryKey: ["search-source-filter"] }); // Search filter list
    },
  });

  const countFor = new Map<string, { events: number; last: unknown }>();
  for (const row of counts.data?.rows ?? []) {
    countFor.set(String(row[0]), { events: Number(row[1]), last: row[2] });
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader
        title="Sources"
        count={`${list.length} ${list.length === 1 ? "source" : "sources"}`}
        secondary={[
          ...(canManage
            ? [
                {
                  label: "Discover",
                  onClick: () => setDiscovering(true),
                  disabled: discovering,
                },
              ]
            : []),
          {
            label: "Refresh counts",
            onClick: () => void counts.refetch(),
            disabled: counts.isFetching,
          },
        ]}
        primary={
          canManage
            ? {
                label: "Add source",
                onClick: () => {
                  setSuggestion((s) => ({ key: s.key + 1, values: {} }));
                  setAdding(true);
                },
                disabled: adding,
              }
            : undefined
        }
      />
      <div className="flex flex-col gap-3 px-5 py-3">
        {adding ? (
          <AddSourceForm
            key={suggestion.key}
            allowedRoots={settings.data?.allowed_roots ?? []}
            initial={suggestion.values}
            onDone={() => {
              setAdding(false);
              void counts.refetch();
            }}
          />
        ) : null}

        {discovering && canManage ? (
          <DiscoverPanel
            allowedRoots={settings.data?.allowed_roots ?? []}
            existingIds={list.map((s) => s.source_id)}
            onUse={(values) => {
              setSuggestion((s) => ({ key: s.key + 1, values }));
              setAdding(true);
            }}
            onClose={() => setDiscovering(false)}
          />
        ) : null}

        {canManage ? <MappingChanges /> : null}

        {sources.isError ? (
          <p role="alert" className="text-sm text-danger">
            {sources.error instanceof ApiError ? sources.error.message : "Could not load sources."}
          </p>
        ) : null}

        <section className="overflow-hidden rounded-card border border-border bg-surface">
          <div className="flex items-center gap-2 border-b border-border bg-surface-head px-3 py-2">
            <SectionTitle>Configured sources</SectionTitle>
            <span className="ml-auto text-sm text-text-muted">
              Status refreshes every 5 seconds
            </span>
          </div>
          {list.length === 0 && !sources.isPending ? (
            <EmptyState
              kind={canManage ? "not-set-up" : "restricted"}
              title={canManage ? "No sources yet" : "No sources to show"}
              detail={
                canManage
                  ? "Add a file or folder your log collector writes to. New lines are read as they arrive."
                  : "None are shared with you yet. An administrator adds sources and shares them through source groups."
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-sm text-text-secondary">
                    <th className="min-w-[8rem] px-3 py-2">Source</th>
                    <th className="min-w-[6rem] px-3 py-2">Path</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2 text-right">Events</th>
                    <th className="px-3 py-2">Data and retention</th>
                    {canManage ? <th className="px-3 py-2" aria-label="Actions" /> : null}
                  </tr>
                </thead>
                <tbody>
                  {list.map((s) => {
                    const c = countFor.get(s.source_id);
                    return (
                      <tr
                        key={s.source_id}
                        id={`source-${s.source_id}`}
                        aria-current={focus === s.source_id ? "true" : undefined}
                        className={`border-b border-border align-top last:border-0 ${focus === s.source_id ? "bg-accent-subtle" : ""}`}
                      >
                        <td className="px-3 py-2.5">
                          <div className="font-mono [overflow-wrap:anywhere]">{s.source_id}</div>
                          <ParserEditor
                            sourceId={s.source_id}
                            templateId={s.template_id}
                            format={s.format}
                            templates={templates.data ?? []}
                            canManage={canManage}
                          />
                          {s.template_id === AUTO_PARSER ? (
                            <ParserMix counts={mixFor.get(s.source_id) ?? new Map()} />
                          ) : null}
                          {s.kind !== "otlp" &&
                          s.kind !== "m365" &&
                          s.kind !== "anthropic" &&
                          s.kind !== "proxmox" ? (
                            <TimeZoneEditor
                              sourceId={s.source_id}
                              value={s.timezone}
                              canManage={canManage}
                            />
                          ) : null}
                        </td>
                        <td className="px-3 py-2.5 font-mono text-sm">
                          {s.kind === "otlp" ? (
                            <OtlpControls
                              sourceId={s.source_id}
                              keepContent={s.otlp_keep_content ?? false}
                              canManage={canManage}
                            />
                          ) : s.kind === "m365" ||
                            s.kind === "anthropic" ||
                            s.kind === "proxmox" ? (
                            <ApiSummary source={s} canManage={canManage} />
                          ) : s.kind === "syslog" ? (
                            <ListenerSummary
                              settings={s.syslog ?? null}
                              listener={s.status.listener ?? null}
                            />
                          ) : s.kind === "loki" ? (
                            <div className="flex flex-col gap-1">
                              <LokiSummary
                                loki={s.loki ?? null}
                                behind={s.status.behind_s ?? null}
                              />
                              <ConnectorSettingsButton source={s} canManage={canManage} />
                            </div>
                          ) : (
                            <>
                              <div className="[overflow-wrap:anywhere]">
                                <WrappedPath path={s.path} />
                              </div>
                              <div className="text-sm text-text-muted">
                                {s.status.files} {s.status.files === 1 ? "file" : "files"}
                                {s.glob !== "*" ? ` · ${s.glob}` : ""}
                              </div>
                            </>
                          )}
                        </td>
                        <td className="px-3 py-2.5">
                          <div className="flex flex-col gap-0.5">
                            <SourceState status={s.status} />
                            <QuietAlert
                              sourceId={s.source_id}
                              quiet={s.quiet}
                              canManage={canManage}
                            />
                            {(s.kind === "otlp" || s.kind === "syslog") && !s.built_in ? (
                              <QuietOkEditor
                                sourceId={s.source_id}
                                value={s.quiet_ok_days ?? null}
                                quietAlert={Boolean(s.quiet)}
                                canManage={canManage}
                                idle={
                                  judged.get(s.source_id)?.idle && overview.data
                                    ? idleText(
                                        quietFrom(judged.get(s.source_id)),
                                        overview.data.generated_at,
                                      )
                                    : null
                                }
                              />
                            ) : null}
                            {s.emits_alerts || s.alert_pause ? (
                              <VendorAlertNotify
                                sourceId={s.source_id}
                                pause={s.alert_pause}
                                canManage={canManage}
                              />
                            ) : null}
                            <ReparseControl
                              sourceId={s.source_id}
                              templateId={s.template_id ?? null}
                              canManage={canManage}
                              pending={s.reparse_pending === true}
                            />
                            <ReparseRulesControl
                              sourceId={s.source_id}
                              canManage={canManage}
                              last={s.reparse_last ?? null}
                            />
                            <GapNote
                              sourceId={s.source_id}
                              gaps={shownGaps(judged.get(s.source_id), gapsOf.get(s.source_id))}
                              now={overview.data?.generated_at ?? new Date().toISOString()}
                            />
                          </div>
                        </td>
                        <td className="px-3 py-2.5 text-right">
                          <div className="font-mono tabular-nums">
                            {c ? c.events.toLocaleString() : "0"}
                          </div>
                          <div
                            className="text-sm text-text-muted"
                            title={typeof c?.last === "string" ? formatTime(c.last) : undefined}
                          >
                            {typeof c?.last === "string"
                              ? `latest ${since(c.last, new Date().toISOString())}`
                              : "no events"}
                          </div>
                        </td>
                        <td className="px-3 py-2.5">
                          <div className="flex flex-col items-start gap-1">
                            {canManage ? (
                              <ClassificationEditor
                                sourceId={s.source_id}
                                value={s.classification}
                              />
                            ) : (
                              <ClassificationBadge value={s.classification} />
                            )}
                            <RetentionEditor
                              sourceId={s.source_id}
                              value={s.retention_days}
                              canManage={canManage}
                            />
                          </div>
                        </td>
                        {canManage ? (
                          <td className="px-3 py-2.5 text-right">
                            {confirming === s.source_id ? (
                              <span className="flex items-center justify-end gap-2 whitespace-nowrap">
                                <button
                                  type="button"
                                  onClick={() => remove.mutate(s.source_id)}
                                  className="rounded border border-danger px-2 py-0.5 text-danger hover:bg-surface-head"
                                >
                                  Remove
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setConfirming(null)}
                                  className="px-2 py-0.5 text-text-secondary"
                                >
                                  Keep
                                </button>
                              </span>
                            ) : (
                              <button
                                type="button"
                                onClick={() => setConfirming(s.source_id)}
                                aria-label={`Remove ${s.source_id}`}
                                className="px-2 py-0.5 text-text-secondary hover:text-text"
                              >
                                Remove
                              </button>
                            )}
                          </td>
                        ) : null}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
        {confirming ? (
          <p className="text-sm text-text-secondary">
            Removing stops reading new lines. Data already collected stays searchable until its
            retention period ends.
          </p>
        ) : null}
      </div>
    </div>
  );
}
