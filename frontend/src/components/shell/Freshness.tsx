import { useEffect, useState } from "react";
import { useIsFetching, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { navigate } from "@/lib/route";

function ago(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return `${h} h ago`;
}

/** "Updated 1 min ago" and Refresh for everything on the page (ADR-0038 row 9). */
export function Freshness() {
  const client = useQueryClient();
  const fetching = useIsFetching();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(t);
  }, []);
  const latest = Math.max(
    0,
    ...client
      .getQueryCache()
      .findAll({ type: "active" })
      .map((q) => q.state.dataUpdatedAt),
  );
  return (
    <>
      {latest ? (
        <span className="hidden text-sm text-white/60 lg:inline">
          Updated {ago(Math.max(now, latest) - latest)}
        </span>
      ) : null}
      <button
        type="button"
        onClick={() => void client.refetchQueries({ type: "active" })}
        disabled={fetching > 0}
        aria-label="Refresh everything on this page"
        title="Refresh everything on this page"
        className="flex h-8 items-center gap-1.5 rounded border border-white/20 px-2.5 hover:bg-white/10 disabled:opacity-60"
      >
        <RefreshCw size={16} aria-hidden className={fetching ? "motion-safe:animate-spin" : ""} />
        <span className="hidden sm:inline">Refresh</span>
      </button>
    </>
  );
}

/** Open alerts the viewer may read; the same number as the rail, for a collapsed rail. */
export function AlertsButton() {
  const q = useQuery({ queryKey: ["alerts", "open"], queryFn: () => api.alerts("open") });
  const n = q.data?.open ?? 0;
  return (
    <a
      href="/alerts"
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        navigate("alerts");
      }}
      aria-label={n ? `Alerts, ${n} open` : "Alerts"}
      title={n ? `${n} open alerts` : "Alerts"}
      className="flex h-8 items-center gap-1.5 rounded border border-white/20 px-2.5 text-white no-underline hover:bg-white/10"
    >
      <Bell size={16} aria-hidden />
      {n ? (
        <span className="rounded-full bg-accent px-1.5 text-xs tabular-nums text-white">{n}</span>
      ) : null}
    </a>
  );
}

/** The optional install name an admin set (Settings > About); nothing when unset. */
export function InstallLabel() {
  const q = useQuery({ queryKey: ["install"], queryFn: api.install, staleTime: 300_000 });
  const name = q.data?.name;
  if (!name) return null;
  return (
    <>
      <span className="hidden text-white/40 lg:inline" aria-hidden="true">
        |
      </span>
      <span className="hidden truncate text-base text-white/75 lg:inline">{name}</span>
    </>
  );
}
