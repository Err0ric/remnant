import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChangePill } from "@/components/ChangePill";
import { PanelTitle } from "@/components/PanelTitle";
import { api, type PageWindow } from "@/lib/api";
import { cn } from "@/lib/cn";
import { navigate, pathFor, type PageId } from "@/lib/route";
import { About } from "./Sections";

interface TileProps {
  label: string;
  /** The headline; a string for "7 of 8". */
  value: ReactNode;
  /** Zero reads muted; a problem reads in the warn color with its words beside it. */
  tone?: "text" | "muted" | "warn";
  /** This window minus the one before; left out when the window before is unknown. */
  change?: number | null;
  context?: ReactNode;
  page: PageId;
  tab?: string;
  opens: string;
  /** How the number is counted, behind the (i) (owner, 2026-11-02). */
  about: string;
}

function Tile({
  label,
  value,
  tone = "text",
  change,
  context,
  page,
  tab,
  opens,
  about,
}: TileProps) {
  return (
    <div data-kpi={label} className="flex min-w-0 flex-col gap-0.5 bg-surface px-3 py-2.5">
      <span className="flex min-w-0 items-start gap-1.5">
        <PanelTitle as="span" className="line-clamp-2 min-w-0" title={label}>
          {label}
        </PanelTitle>
        <About text={about} />
      </span>
      <span className="flex flex-wrap items-center gap-x-2">
        <a
          href={`${pathFor(page)}${tab ? `#${tab}` : ""}`}
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey) return;
            e.preventDefault();
            navigate(page, tab);
          }}
          aria-label={`${label}: ${typeof value === "string" || typeof value === "number" ? value : ""}. Open ${opens}`}
          className={cn(
            "text-kpi tabular-nums no-underline hover:underline min-[1500px]:text-kpi-lg",
            tone === "muted" ? "text-text-muted" : tone === "warn" ? "text-warn" : "text-text",
          )}
        >
          {value}
        </a>
        {change !== null && change !== undefined ? (
          <ChangePill
            change={change}
            spoken={`${change === 0 ? "same as" : `${change > 0 ? "up" : "down"} ${Math.abs(change).toLocaleString()} from`} the window before`}
          />
        ) : null}
      </span>
      {context ? <span className="line-clamp-2 text-sm text-text-muted">{context}</span> : null}
    </div>
  );
}

const num = (n: number) => n.toLocaleString();

/** The Dashboard's KPI strip for the window (DESIGN.md 6.3): open alerts, failed sign-ins,
 * sign-ins outside approved countries, AI services in use with how many are to review, and
 * sources healthy (the same server count as the Health tile, in the warn color when not
 * all). A tile shows only when the viewer has its source. From the queries the page already
 * makes; every number opens the place to act on it. */
export function KpiStrip({ window, days }: { window: PageWindow; days: number }) {
  const count = useQuery({ queryKey: ["alerts", "count"], queryFn: api.alertCount });
  const identity = useQuery({
    queryKey: ["dashboard-sections", window, "identity"],
    queryFn: () => api.dashboardSections(window, "identity"),
    refetchInterval: 300_000,
  });
  const watch = useQuery({
    queryKey: ["ai-watch", days],
    queryFn: () => api.aiWatchSummary(days),
    refetchInterval: 300_000,
  });
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 60_000,
  });
  const id = identity.data?.identity ?? null;
  const services = watch.data?.cards.find((c) => c.key === "services");
  const inUse = watch.data?.services_in_use;
  const toReview = services?.unreviewed ?? 0;
  const summary = overview.data?.source_summary;
  const tiles: ReactNode[] = [];
  if (count.data) {
    const open = count.data.open;
    tiles.push(
      <Tile
        key="alerts"
        label="Open alerts"
        value={num(open)}
        tone={open ? "text" : "muted"}
        context={open ? `${num(count.data.by_severity?.high ?? 0)} High` : "Nothing open"}
        page="alerts"
        opens="Alerts"
        about="Alerts that are open now in sources you can read, whatever the window above. One per rule, search, service, or source and day; repeats are counted once."
      />,
    );
  }
  if (id) {
    tiles.push(
      <Tile
        key="failed"
        label="Failed sign-ins"
        value={num(id.failed.value)}
        tone={id.failed.value ? "text" : "muted"}
        change={id.failed.before === null ? null : id.failed.value - id.failed.before}
        page="m365"
        tab="sign-ins"
        opens="Microsoft 365 sign-ins"
        about="Microsoft 365 sign-ins that failed in the window, as in the Identity section below. Interrupted and expired attempts are not counted as failures."
      />,
    );
    tiles.push(
      id.outside ? (
        <Tile
          key="outside"
          label="Sign-ins outside approved countries"
          value={num(id.outside.value)}
          tone={id.outside.value ? "text" : "muted"}
          change={id.outside.before === null ? null : id.outside.value - id.outside.before}
          page="m365"
          tab="sign-ins"
          opens="Microsoft 365 sign-ins"
          about="Successful Microsoft 365 sign-ins in the window from a country that is not in your approved countries, placed by the GeoIP file on this server."
        />
      ) : (
        <Tile
          key="outside"
          label="Sign-ins outside approved countries"
          value="Not set"
          tone="muted"
          context="Set approved countries to count these"
          page="enrichment"
          opens="Enrichment"
          about="Counted once approved countries are set on Enrichment: successful sign-ins from any other country, placed by the GeoIP file on this server."
        />
      ),
    );
  }
  if (inUse) {
    tiles.push(
      <Tile
        key="ai"
        label="AI services in use"
        value={num(inUse)}
        context={toReview ? `${num(toReview)} to review` : "All reviewed"}
        page="ai"
        tab={toReview ? "inventory" : "services"}
        opens="AI usage"
        about="AI services with any use in the window in sources you can read, whatever their review status. To review counts those nobody has marked Approved or Not approved yet."
      />,
    );
  }
  if (summary?.total) {
    const all = summary.healthy === summary.total;
    tiles.push(
      <Tile
        key="sources"
        label="Sources healthy"
        value={`${num(summary.healthy)} of ${num(summary.total)}`}
        tone={all ? "text" : "warn"}
        context={all ? null : "Not all sending; open Health"}
        page="health"
        tab="sources"
        opens="Health"
        about="Sources you can read that are sending and being read without a problem, of all your sources. The same count as the Sources tile on Health."
      />,
    );
  }
  if (!tiles.length) return null;
  return (
    <section
      aria-label="Key numbers"
      className="grid grid-cols-2 gap-px overflow-hidden rounded-card border border-border bg-border md:grid-cols-3 xl:grid-cols-5"
    >
      {tiles}
    </section>
  );
}
