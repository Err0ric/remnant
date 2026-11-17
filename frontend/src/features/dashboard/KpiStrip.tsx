import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { KpiTile } from "@/components/KpiTile";
import { api, type PageWindow } from "@/lib/api";
import { cn } from "@/lib/cn";
import { kpiKeys, type DashboardShape } from "./shape";

const num = (n: number) => n.toLocaleString();

const COLS: Record<number, string> = {
  1: "xl:grid-cols-1",
  2: "xl:grid-cols-2",
  3: "xl:grid-cols-3",
  4: "xl:grid-cols-4",
  5: "xl:grid-cols-5",
};

const ABOUT: Record<string, string> = {
  alerts:
    "Alerts that are open now in sources you can read, whatever the window above. One per rule, search, service, or source and day; repeats are counted once.",
  failed:
    "Microsoft 365 sign-ins that failed in the window, as in the Identity section below. Interrupted and expired attempts are not counted as failures.",
  outside:
    "Successful Microsoft 365 sign-ins in the window from a country that is not in your approved countries, placed by the GeoIP file on this server.",
  notSet:
    "Counted once approved countries are set on Enrichment: successful sign-ins from any other country, placed by the GeoIP file on this server.",
  ai: "AI services with any use in the window in sources you can read, whatever their review status. Unreviewed counts those of them nobody has marked Approved or Not approved yet; the Inventory also lists MCP servers to review.",
  sources:
    "Sources you can read that are sending and being read without a problem, of all your sources. A source marked Quiet is normal counts as healthy while it is idle inside its days. The same count as the Sources tile on Health.",
};

const LABEL: Record<string, string> = {
  alerts: "Open alerts",
  failed: "Failed sign-ins",
  outside: "Sign-ins outside approved countries",
  ai: "AI services in use",
  sources: "Sources healthy",
};

/** The Dashboard's KPI strip for the window (DESIGN.md 6.3): open alerts, failed sign-ins,
 * sign-ins outside approved countries, AI services in use with how many are to review, and
 * sources healthy (the same server count as the Health tile, in the warn color when not
 * all). Its tiles come from the viewer's sources (`shape`), so the strip has its final
 * number of tiles from the first paint: each is a skeleton until its own answer arrives,
 * and one whose answer has nothing to count says "Not available" in its place. From the
 * queries the page already makes; every number opens the place to act on it. */
export function KpiStrip({
  window,
  days,
  shape,
}: {
  window: PageWindow;
  days: number;
  shape: DashboardShape;
}) {
  const count = useQuery({ queryKey: ["alerts", "count"], queryFn: api.alertCount });
  const identity = useQuery({
    queryKey: ["dashboard-sections", window, "identity"],
    queryFn: () => api.dashboardSections(window, "identity"),
    refetchInterval: 300_000,
    enabled: shape.m365,
  });
  const watch = useQuery({
    queryKey: ["ai-watch", days],
    queryFn: () => api.aiWatchSummary(days),
    refetchInterval: 300_000,
    enabled: shape.any,
  });
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 60_000,
    enabled: shape.any,
  });
  const keys = kpiKeys(shape);
  /** The tile's place while its answer is not there, or could not be read. */
  const waiting = (
    key: string,
    q: { isError: boolean; data: unknown; refetch: () => unknown },
  ): ReactNode =>
    q.isError && !q.data ? (
      <KpiTile
        key={key}
        label={LABEL[key] ?? key}
        value=""
        about={ABOUT[key]}
        failed={() => void q.refetch()}
      />
    ) : (
      <KpiTile
        key={key}
        label={LABEL[key] ?? key}
        value=""
        about={ABOUT[key]}
        loading
        // Its count has a change beside it and no context line (its label takes two).
        contextLine={key !== "outside"}
      />
    );
  const missing = (key: string, about: string): ReactNode => (
    <KpiTile key={key} label={LABEL[key] ?? key} value="Not available" tone="muted" about={about} />
  );
  const tile = (key: string): ReactNode => {
    if (key === "alerts") {
      if (!count.data) return waiting(key, count);
      const open = count.data.open;
      return (
        <KpiTile
          key={key}
          label={LABEL.alerts ?? key}
          value={num(open)}
          tone={open ? "text" : "muted"}
          context={open ? `${num(count.data.by_severity?.high ?? 0)} High` : "Nothing open"}
          page="alerts"
          opens="Alerts"
          about={ABOUT.alerts}
        />
      );
    }
    if (key === "failed" || key === "outside") {
      if (!identity.data) return waiting(key, identity);
      const id = identity.data.identity;
      if (!id) return missing(key, ABOUT[key] ?? "");
      if (key === "failed")
        return (
          <KpiTile
            key={key}
            label={LABEL.failed ?? key}
            value={num(id.failed.value)}
            tone={id.failed.value ? "text" : "muted"}
            change={id.failed.before === null ? null : id.failed.value - id.failed.before}
            page="m365"
            tab="sign-ins"
            opens="Microsoft 365 sign-ins"
            about={ABOUT.failed}
          />
        );
      return id.outside ? (
        <KpiTile
          key={key}
          label={LABEL.outside ?? key}
          value={num(id.outside.value)}
          tone={id.outside.value ? "text" : "muted"}
          change={id.outside.before === null ? null : id.outside.value - id.outside.before}
          page="m365"
          tab="sign-ins"
          opens="Microsoft 365 sign-ins"
          about={ABOUT.outside}
        />
      ) : (
        <KpiTile
          key={key}
          label={LABEL.outside ?? key}
          value="Not set"
          tone="muted"
          context="Set approved countries to count these"
          page="enrichment"
          opens="Enrichment"
          about={ABOUT.notSet}
        />
      );
    }
    if (key === "ai") {
      if (!watch.data) return waiting(key, watch);
      const inUse = watch.data.services_in_use ?? 0;
      const toReview = watch.data.cards.find((c) => c.key === "services")?.unreviewed ?? 0;
      return (
        <KpiTile
          key={key}
          label={LABEL.ai ?? key}
          value={num(inUse)}
          tone={inUse ? "text" : "muted"}
          // Services in the window only: worded apart from the rail's and the Inventory's
          // "N to review", which also counts MCP servers (owner, 2026-11-16).
          context={
            !inUse
              ? "None in this window"
              : toReview
                ? `${num(toReview)} of them unreviewed`
                : "All reviewed"
          }
          page="ai"
          tab={toReview ? "inventory" : "services"}
          opens="AI usage"
          about={ABOUT.ai}
        />
      );
    }
    if (!overview.data) return waiting(key, overview);
    const summary = overview.data.source_summary;
    if (!summary?.total) return missing(key, ABOUT.sources ?? "");
    const all = summary.healthy === summary.total;
    return (
      <KpiTile
        key={key}
        label={LABEL.sources ?? key}
        value={`${num(summary.healthy)} of ${num(summary.total)}`}
        tone={all ? "text" : "warn"}
        context={
          !all
            ? "Not all sending; open Health"
            : summary.idle
              ? `${summary.idle} idle (normal)`
              : null
        }
        page="health"
        tab="sources"
        opens="Health"
        about={ABOUT.sources}
      />
    );
  };
  return (
    <section
      aria-label="Key numbers"
      data-tiles={keys.length}
      className={cn(
        "grid grid-cols-2 gap-px overflow-hidden rounded-card border border-border bg-border md:grid-cols-3",
        // One row of exactly its tiles from 1280 px, so no empty cell shows the divider color.
        COLS[keys.length] ?? "xl:grid-cols-5",
      )}
    >
      {keys.map(tile)}
    </section>
  );
}
