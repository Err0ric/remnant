import { useQuery } from "@tanstack/react-query";
import { api, type SectionKpi } from "@/lib/api";
import { navigate, type PageId } from "@/lib/route";

/** Real failed sign-ins need attention above this many in the window, and only when they
 * are more than twice the window before (when it is known). */
export const FAILED_SIGNINS_THRESHOLD = 20;

export interface AttentionItem {
  key: string;
  count: number;
  /** "3 unreviewed AI services" */
  text: string;
  page: PageId;
  tab?: string;
}

const plural = (n: number, one: string, many: string) =>
  `${n.toLocaleString()} ${n === 1 ? one : many}`;

/** Failed sign-ins worth a look: over the threshold, and well above the window before. */
export function failedSigninsItem(kpi: SectionKpi | null | undefined): AttentionItem | null {
  if (!kpi || kpi.value <= FAILED_SIGNINS_THRESHOLD) return null;
  if (kpi.before !== null && kpi.before !== undefined && kpi.value <= 2 * kpi.before) return null;
  return {
    key: "failed",
    count: kpi.value,
    text: plural(kpi.value, "real failed sign-in", "real failed sign-ins"),
    page: "m365",
    tab: "sign-ins",
  };
}

/** Items with a count, in the order given; empty ones are left out. */
export function attentionItems(
  parts: (AttentionItem | null | undefined | false)[],
): AttentionItem[] {
  return parts.filter((p): p is AttentionItem => !!p && p.count > 0);
}

export function count(
  key: string,
  n: number | null | undefined,
  one: string,
  many: string,
  page: PageId,
  tab?: string,
): AttentionItem | null {
  return n ? { key, count: n, text: plural(n, one, many), page, tab } : null;
}

/** Open alerts the viewer may read, as an attention item. Shares the Alerts page's query. */
export function useOpenAlertsItem(): AttentionItem | null {
  const q = useQuery({ queryKey: ["alerts", "open"], queryFn: () => api.alerts("open") });
  return count("alerts", q.data?.open, "open alert", "open alerts", "alerts");
}

/** One line at the top of a page: what needs someone, as counts that open the place to act
 * (owner, 2026-11-02). "Nothing needs attention" when nothing does; hidden while loading. */
export function NeedsAttention({ items, loading }: { items: AttentionItem[]; loading?: boolean }) {
  if (loading) return null;
  return (
    <section
      aria-label="Needs attention"
      className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-card border border-border bg-surface px-3 py-2 text-sm"
    >
      {items.length ? (
        <>
          <span className="font-semibold">Needs attention</span>
          {items.map((i) => (
            <button
              key={i.key}
              type="button"
              onClick={() => navigate(i.page, i.tab)}
              className="text-accent-text hover:underline"
            >
              {i.text}
            </button>
          ))}
        </>
      ) : (
        <span className="text-text-muted">Nothing needs attention</span>
      )}
    </section>
  );
}

/** The Dashboard's strip: unreviewed AI services, risky mail rules, blocked consents, open
 * alerts, and real failed sign-ins over the threshold, from the queries the page already
 * makes. */
export function DashboardAttention({
  window,
  days,
}: {
  window: "24h" | "7d" | "30d";
  days: number;
}) {
  const watch = useQuery({
    queryKey: ["ai-watch", days],
    queryFn: () => api.aiWatchSummary(days),
    refetchInterval: 300_000,
  });
  const identity = useQuery({
    queryKey: ["dashboard-sections", window, "identity"],
    queryFn: () => api.dashboardSections(window, "identity"),
    refetchInterval: 300_000,
  });
  const alerts = useOpenAlertsItem();
  const id = identity.data?.identity;
  const unreviewed = watch.data?.cards.find((c) => c.key === "services")?.unreviewed;
  const items = attentionItems([
    alerts,
    count("unreviewed", unreviewed, "unreviewed AI service", "unreviewed AI services", "ai"),
    count("mail", id?.inbox_rules.value, "risky mail rule", "risky mail rules", "m365", "mail"),
    count(
      "consents",
      id?.consents.extra,
      "blocked app consent",
      "blocked app consents",
      "m365",
      "apps",
    ),
    failedSigninsItem(id?.failed),
  ]);
  return <NeedsAttention items={items} loading={watch.isLoading || identity.isLoading} />;
}
