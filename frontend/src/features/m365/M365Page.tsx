import { Skeleton } from "@/components/Skeleton";
import { useQuery } from "@tanstack/react-query";
import { COUNTED, M365_COUNT_COUNTED, OUTCOME_COUNTED } from "@/features/dashboard/counted";
import { useState, type ReactNode } from "react";
import { api, type M365Overview, type PageWindow } from "@/lib/api";
import { cn } from "@/lib/cn";
import { navigate, useTab } from "@/lib/route";
import { EmptyState } from "@/components/EmptyState";
import { Truncate } from "@/components/Truncate";
import { PageHeader } from "@/components/shell/PageHeader";
import { InlineError } from "@/components/InlineError";
import { AdminChanges } from "./AdminChanges";
import { MailRules } from "./MailRules";
import {
  About,
  DrillScope,
  DRILL,
  Kpi,
  SetCountries,
  Top,
  useDrill,
} from "@/features/dashboard/Sections";
import { startIndex, TrendChart, TrendLegend } from "@/features/dashboard/TrendChart";
import { compareLine } from "@/features/dashboard/History";
import { WINDOWS, previousPhrase } from "@/features/dashboard/pageWindow";
import { PanelTitle } from "@/components/PanelTitle";
import { EventList } from "./EventList";
import { SignIns } from "./SignIns";
import {
  attentionItems,
  count,
  NeedsAttention,
  useOpenAlertsItem,
} from "@/features/dashboard/NeedsAttention";
import { notCountedExtra, useSignInAbout } from "./signInCounting";

const KEY = "m365.window";

function readWindow(): PageWindow {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "24h" || v === "7d" || v === "30d" ? v : "7d";
  } catch {
    return "7d";
  }
}

const hourFmt = (d: Date) => d.toLocaleTimeString("en-US", { hour: "numeric" });
const dayFmt = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });

const VIEW_LABEL: Record<string, string> = {
  "sign-ins": "Microsoft 365 sign-ins",
  mail: "Microsoft 365 mail",
  admin: "Microsoft 365 admin",
};

/** The Microsoft 365 views of Logs (ADR-0052 section 3.3): Sign-ins, Mail, and Admin, each
 * a set of lists the server builds and runs on the caller's own sources (rule 13), so they
 * need no SQL access and show no editor. Microsoft 365 has no area of its own: its
 * numbers are in the Dashboard's Identity section and its apps in the AI usage Inventory.
 * One time window for the three views, remembered in this browser; every number opens its
 * rows (ADR-0039). */
export function M365Page() {
  const tab = useTab() ?? "sign-ins";
  const [win, setWin] = useState<PageWindow>(readWindow);
  const q = useQuery({
    queryKey: ["m365-overview", win],
    queryFn: () => api.m365Overview(win),
    refetchInterval: 300_000,
  });
  const pick = (w: PageWindow) => {
    setWin(w);
    try {
      window.localStorage.setItem(KEY, w);
    } catch {
      // Storage blocked: the window still applies for this page view.
    }
  };
  const m = q.data;
  const view = VIEW_LABEL[tab] ?? VIEW_LABEL["sign-ins"];
  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageHeader title="Logs" count={view} />
      <div className="flex flex-col gap-4 p-5">
        <div className="flex flex-wrap items-center gap-3">
          <div role="group" aria-label="Time window" className="flex rounded border border-border">
            {WINDOWS.map((w) => (
              <button
                key={w.id}
                type="button"
                aria-pressed={w.id === win}
                onClick={() => pick(w.id)}
                className={cn(
                  "h-8 px-3 text-sm first:rounded-l last:rounded-r",
                  w.id === win
                    ? "bg-surface-head font-semibold text-text"
                    : "text-text-secondary hover:text-text",
                )}
              >
                {w.label}
              </button>
            ))}
          </div>
          {m?.has_source ? (
            <span className="text-sm text-text-muted">
              {compareLine(m.history.compared, m.history.since, previousPhrase(win))}
            </span>
          ) : null}
        </div>
        {q.isLoading ? (
          <Skeleton label={view ?? "this view"} block="h-64" />
        ) : q.isError && !m ? (
          <section aria-label={view} className="rounded-card border border-border bg-surface">
            <InlineError
              what={view ?? "This view"}
              error={q.error}
              onRetry={() => void q.refetch()}
              retrying={q.isFetching}
            />
          </section>
        ) : !m ? null : !m.has_source ? (
          <EmptyState
            kind="not-set-up"
            title="Needs a Microsoft 365 source"
            detail="Add the Microsoft 365 connector, or a file read with a Microsoft 365 template. If one exists, you may not have access to it."
            action={{ label: "Add a source", onClick: () => navigate("sources") }}
          />
        ) : (
          <DrillScope
            bounds={m}
            area={`Logs > ${view}`}
            history={m.history}
            before={previousPhrase(win)}
          >
            {tab === "mail" ? (
              <>
                <MailRules m={m} />
                <EventList title="DLP matches" list="dlp" sql={m.lists.dlp} m={m} />
              </>
            ) : tab === "admin" ? (
              <>
                <AdminChanges m={m} />
                {/* The event lists of the old Apps tab: consents and registrations are
                    changes an administrator made. The register of apps is the Inventory. */}
                <EventList title="App consents" list="consents" sql={m.lists.consents} m={m} />
                <EventList
                  title="App registrations"
                  list="registrations"
                  sql={m.lists.registrations}
                  m={m}
                />
              </>
            ) : (
              <>
                {/* What the Microsoft 365 Overview showed: the Dashboard's Identity section
                    has its headline numbers, and the rest of it is about sign-ins. */}
                <Overview m={m} />
                <SignIns m={m} />
              </>
            )}
          </DrillScope>
        )}
      </div>
    </div>
  );
}

function Box({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section aria-label={label} className="rounded-card border border-border bg-surface">
      {children}
    </section>
  );
}

function Overview({ m }: { m: M365Overview }) {
  const drill = useDrill();
  const about = useSignInAbout();
  const alerts = useOpenAlertsItem();
  const attention = attentionItems([
    alerts,
    count(
      "mail",
      m.counts.find((c) => c.key === "mail_rules")?.kpi.value,
      "risky mail rule",
      "risky mail rules",
      "m365",
      "mail",
    ),
    count(
      "consents",
      m.consents?.extra,
      "blocked app consent",
      "blocked app consents",
      "m365",
      "admin",
    ),
    // Not the failed sign-ins item: its list is this view, right under these numbers, so
    // a link to it would go nowhere.
  ]);
  const kpis = [
    <Kpi key="s" label="Sign-ins" kpi={m.sign_ins} about={COUNTED.signIns} />,
    <Kpi
      key="f"
      label="Failed sign-ins"
      kpi={m.failed}
      noun="failed sign-ins"
      about={about}
      extra={notCountedExtra(m.failed?.extra, m.failed_other)}
    />,
    <Kpi
      key="b"
      label="Blocked by policy"
      kpi={m.blocked ?? null}
      about={COUNTED.blocked}
      noun="blocked sign-ins"
      context="Conditional Access (53003); also in Failed sign-ins"
    />,
    <Kpi
      key="o"
      label="Sign-ins outside approved countries"
      kpi={m.outside}
      about={COUNTED.outside}
      context={m.outside ? "Successful sign-ins, by GeoIP of the address" : undefined}
      empty={<SetCountries />}
    />,
    <Kpi
      key="r"
      label="Risky sign-ins"
      kpi={m.risky}
      context="Medium or high risk"
      about={COUNTED.risky}
    />,
    <Kpi
      key="c"
      label="App consents granted"
      kpi={m.consents}
      about={COUNTED.consents}
      noun="consents"
      extra={
        m.consents?.extra
          ? {
              text: `${m.consents.extra.toLocaleString()} blocked`,
              label: "Blocked app consents",
              noun: "blocked consents",
            }
          : undefined
      }
    />,
    <Kpi
      key="a"
      label="Admin changes"
      kpi={m.admin_changes}
      about={COUNTED.adminChanges}
      noun="changes"
      context="Role grants and Conditional Access edits"
    />,
  ];
  return (
    <>
      <NeedsAttention items={attention} />
      <Box label="Summary">
        <div className="grid grid-cols-2 gap-px bg-border lg:grid-cols-4 min-[1400px]:grid-cols-7 [&>*:last-child]:col-span-2 min-[1400px]:[&>*:last-child]:col-span-1">
          {kpis}
        </div>
        <ul
          aria-label="Counts"
          className="flex flex-wrap gap-x-6 gap-y-1 border-t border-border px-3 py-2 text-sm"
        >
          {m.counts.map((c) => {
            const open = drill(c.kpi.drill, c.label);
            return (
              <li key={c.key} data-kpi={c.label} className="flex items-baseline gap-1.5">
                <span className="text-text-secondary">{c.label}</span>
                <About
                  text={
                    M365_COUNT_COUNTED[c.key] ??
                    `${c.label} from the Microsoft 365 Management Activity API, one per record, in this window.`
                  }
                />
                <button
                  type="button"
                  data-drill=""
                  onClick={open}
                  title={`Open ${c.kpi.value.toLocaleString()} events in Logs`}
                  className={cn(DRILL, "font-mono font-semibold tabular-nums")}
                >
                  {c.kpi.value.toLocaleString()}
                </button>
                {c.kpi.extra != null ? (
                  <button
                    type="button"
                    data-drill=""
                    onClick={drill(c.kpi.extra_drill, "Organizing mail rules")}
                    title="Rules that file mail into named folders: not counted as risky"
                    className={cn(DRILL, "text-text-muted")}
                  >
                    ({c.kpi.extra.toLocaleString()} organizing)
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      </Box>
      {m.outcome ? <Outcome m={m} /> : null}
      <div className="grid gap-4 lg:grid-cols-3">
        <Box label="Failure reasons">
          <div className="p-3">
            <Top
              title="Failure reasons"
              columns={["Reason", "Failed"]}
              rows={m.reasons}
              cells={(r) => [<RowLink key="r" row={r} />, r.count.toLocaleString()]}
              empty="No failed sign-ins in this window."
            />
          </div>
        </Box>
        <Box label="Sign-ins outside approved countries">
          <div className="p-3">
            {m.approved_set ? (
              <Top
                title="Sign-ins outside approved countries"
                columns={["Country", "People", "Sign-ins"]}
                rows={m.outside_top}
                cells={(r) => [<RowLink key="c" row={r} />, r.detail, r.count.toLocaleString()]}
                empty="No sign-ins outside approved countries in this window."
              />
            ) : (
              <>
                <PanelTitle className="mb-2">Sign-ins outside approved countries</PanelTitle>
                <p className="text-sm text-text-secondary">
                  <SetCountries /> to see sign-ins from other countries.
                </p>
              </>
            )}
          </div>
        </Box>
        <Box label="Apps signed in to">
          <div className="p-3">
            <Top
              title="Apps signed in to"
              columns={["App", "Sign-ins"]}
              // The app name gets the card's free space, cut in the middle (D257).
              widths={["", "w-24"]}
              rows={m.apps}
              cells={(r) => [<RowLink key="a" row={r} cut />, r.count.toLocaleString()]}
              empty="No sign-ins in this window."
            />
          </div>
        </Box>
      </div>
    </>
  );
}

interface RowLinkProps {
  row: M365Overview["reasons"][number];
  /** A long name is cut in the middle, the whole one in the title (D257). */
  cut?: boolean;
}

function RowLink({ row, cut = false }: RowLinkProps) {
  const drill = useDrill();
  const open = drill(row.drill, row.label);
  const text = cut ? <Truncate value={row.label} kind="name" inLink={!!open} /> : row.label;
  return open ? (
    <button
      type="button"
      data-drill=""
      onClick={open}
      title={`${cut ? `${row.label}\n` : ""}Open ${row.count.toLocaleString()} events in Logs`}
      aria-label={cut ? row.label : undefined}
      className={cn(DRILL, "max-w-full truncate text-left")}
    >
      {text}
    </button>
  ) : (
    <>{text}</>
  );
}

/** Succeeded, failed, interrupted, expired, and other (D158; failures in warn, the rest
 * muted, never red): one bar of the window's split, then each failure class over time. */
function Outcome({ m }: { m: M365Overview }) {
  const drill = useDrill();
  const o = m.outcome;
  if (!o) return null;
  const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);
  const parts = [
    { label: "Succeeded", n: sum(o.succeeded), color: "accent", sql: o.drill_succeeded },
    { label: "Failed", n: sum(o.failed), color: "warn", sql: o.drill_failed },
    { label: "Interrupted", n: sum(o.interrupted), color: "text-muted", sql: o.drill_interrupted },
    {
      label: "Expired",
      n: sum(o.expired ?? []),
      color: "series-neutral",
      sql: o.drill_expired ?? o.drill_failed,
    },
    {
      label: "Other",
      n: sum(o.other ?? []),
      color: "text-secondary",
      sql: o.drill_other ?? o.drill_failed,
    },
  ];
  const total = Math.max(1, sum(parts.map((p) => p.n)));
  const hourly = m.window !== "30d";
  const at = (i: number) => new Date(o.points[i] ?? "");
  const name = (i: number) => (hourly ? `${dayFmt(at(i))}, ${hourFmt(at(i))}` : dayFmt(at(i)));
  const begin = startIndex(o.points, m.history.since);
  return (
    <Box label="Sign-in outcomes">
      <div className="grid gap-4 p-3 lg:grid-cols-[2fr_3fr]">
        <div className="min-w-0">
          <PanelTitle className="mb-2">Sign-in outcomes</PanelTitle>
          <div className="flex h-5 overflow-hidden rounded-sm bg-border" aria-hidden="true">
            {parts.map((p) =>
              p.n ? (
                <div
                  key={p.label}
                  style={{ width: `${(p.n / total) * 100}%`, background: `var(--${p.color})` }}
                />
              ) : null,
            )}
          </div>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {parts.map((p) => (
              <li key={p.label} data-kpi={p.label} className="flex items-center gap-2">
                <span
                  aria-hidden="true"
                  className="inline-block size-2.5 rounded-sm"
                  style={{ background: `var(--${p.color})` }}
                />
                <span className="text-text-secondary">{p.label}</span>
                <About text={OUTCOME_COUNTED[p.label] ?? `${p.label} sign-ins in this window.`} />
                <button
                  type="button"
                  data-drill=""
                  onClick={drill(p.sql, `${p.label} sign-ins`)}
                  title={`Open ${p.n.toLocaleString()} events in Logs`}
                  className={cn(DRILL, "ml-auto font-mono tabular-nums")}
                >
                  {p.n.toLocaleString()}
                </button>
                <span className="w-12 text-right font-mono text-text-muted tabular-nums">
                  {((p.n / total) * 100).toFixed(1)}%
                </span>
              </li>
            ))}
          </ul>
        </div>
        <TrendChart
          title={`Failed sign-ins by class per ${hourly ? "hour" : "day"}`}
          note={begin !== undefined ? `no data before ${dayFmt(at(begin))}` : undefined}
          firstWithData={begin}
          partial="so far"
          stacked
          series={[
            { key: "o", label: "Other", values: o.other ?? [], color: "text-secondary" },
            { key: "e", label: "Expired", values: o.expired ?? [], color: "series-neutral" },
            // Not the muted gray: that is the dashed line of the window before.
            { key: "i", label: "Interrupted", values: o.interrupted, color: "accent-text" },
            { key: "f", label: "Failed", values: o.failed, color: "warn" },
          ]}
          pointLabel={name}
          details={(i) =>
            [
              { label: "Top user", value: o.top_user?.[i] ?? "" },
              { label: "Top app", value: o.top_app?.[i] ?? "" },
            ].filter((d) => d.value)
          }
          axisLabel={(i) => (m.window === "24h" ? hourFmt(at(i)) : dayFmt(at(i)))}
          summary={`Failed sign-ins by class per ${hourly ? "hour" : "day"}: ${sum(
            o.failed,
          ).toLocaleString()} failed, ${sum(o.interrupted).toLocaleString()} interrupted, ${sum(
            o.expired ?? [],
          ).toLocaleString()} expired, ${sum(o.other ?? []).toLocaleString()} other`}
          legend={
            <TrendLegend
              items={[
                { label: "Failed", color: "warn" },
                { label: "Interrupted", color: "text-muted" },
                { label: "Expired", color: "series-neutral" },
                { label: "Other", color: "text-secondary" },
              ]}
            />
          }
          onOpen={(i) =>
            drill(o.drill_failed, `Failed sign-ins, ${name(i)}`, {
              from: o.points[i] ?? m.start,
              to: o.points[i + 1] ?? m.end,
            })?.()
          }
        />
      </div>
    </Box>
  );
}
