import { useQuery } from "@tanstack/react-query";
import { EntityLink } from "@/components/EntityLink";
import { LoadFailed } from "@/components/LoadFailed";
import { api, type AccountTier } from "@/lib/api";
import { cn } from "@/lib/cn";
import { navigate } from "@/lib/route";
import { since, stamp } from "@/features/overview/time";

/** The row labels ADR-0030's amendment names, in its order. */
export const TIER_LABEL: Record<AccountTier, string> = {
  company_confirmed: "Company account, confirmed by sign-in",
  company_reported: "Company account (reported by device)",
  company_unconfirmed: "Reported company account, not confirmed by sign-in",
  personal: "Personal Claude account",
  not_checked: "Not checked",
};

const SHORT: Record<AccountTier, string> = {
  company_confirmed: "Company, confirmed",
  company_reported: "Company, reported",
  company_unconfirmed: "Company, not confirmed",
  personal: "Personal",
  not_checked: "Not checked",
};

const ORDER: AccountTier[] = [
  "company_confirmed",
  "company_reported",
  "company_unconfirmed",
  "personal",
  "not_checked",
];

/** A tier as text with a neutral or warn tone: personal and unconfirmed want a look, but
 * nothing acts on a tier (T5), so no severity colors. */
export function TierBadge({ tier }: { tier: AccountTier }) {
  const look = tier === "personal" || tier === "company_unconfirmed";
  return (
    <span
      title={TIER_LABEL[tier]}
      className={cn(
        "whitespace-nowrap rounded-badge px-1.5 py-px text-xs",
        look ? "bg-surface-head text-warn" : "bg-surface-head text-text-secondary",
      )}
    >
      {SHORT[tier]}
    </span>
  );
}

/** Agents > Accounts (ADR-0038 section 6): Claude accounts by tier, with devices, the
 * people the computers belong to, and the evidence behind each tier. */
export function AccountsCard() {
  const q = useQuery({ queryKey: ["agent-accounts"], queryFn: () => api.agentAccounts(30) });
  const now = new Date().toISOString();
  const d = q.data;
  return (
    <section
      aria-label="Claude accounts"
      className="overflow-hidden rounded-card border border-border bg-surface"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-surface-head px-3 py-2">
        <h2 className="text-base font-semibold">Claude accounts</h2>
        <span className="text-sm text-text-muted">
          Reported by the hooks plugin on each device, last 30 days. A company email is confirmed by
          an Entra sign-in to Claude by the same person.
        </span>
      </div>
      {q.isLoading ? (
        <div aria-busy="true" className="h-40 animate-pulse" />
      ) : q.isError ? (
        <LoadFailed
          what="Claude accounts"
          error={q.error}
          onRetry={() => void q.refetch()}
          retrying={q.isFetching}
        />
      ) : d ? (
        <>
          <ul
            aria-label="Accounts by tier"
            className="grid grid-cols-2 gap-px border-b border-border bg-border sm:grid-cols-5"
          >
            {ORDER.map((t) => (
              <li key={t} className="flex flex-col gap-0.5 bg-surface px-3 py-2">
                <span className="text-sm text-text-secondary">{SHORT[t]}</span>
                <span className="text-kpi tabular-nums">{(d.counts[t] ?? 0).toLocaleString()}</span>
              </li>
            ))}
          </ul>
          {!d.domains_set ? (
            <p role="note" className="border-b border-border px-3 py-2 text-sm text-text-secondary">
              Organization email domains are not set, so no account can count as a company account.{" "}
              <button
                type="button"
                onClick={() => navigate("identities")}
                className="text-accent-text hover:underline"
              >
                Set organization domains
              </button>
            </p>
          ) : null}
          {d.rows.length === 0 ? (
            <p className="px-3 py-4 text-sm text-text-secondary">
              No Claude Code or Cowork sessions in the last 30 days. The hooks plugin reports the
              account once it is installed.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-text-secondary">
                    <th className="px-3 py-2 font-semibold">Account</th>
                    <th className="px-3 py-2 font-semibold">Tier</th>
                    <th className="px-3 py-2 font-semibold">Evidence</th>
                    <th className="px-3 py-2 font-semibold">Devices</th>
                    <th className="px-3 py-2 text-right font-semibold">Sessions</th>
                    <th className="px-3 py-2 font-semibold">Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {d.rows.map((r) => (
                    <tr
                      key={`${r.email ?? ""}:${r.devices.join(",")}`}
                      data-row={r.email ?? "none"}
                      className="border-b border-border last:border-0"
                    >
                      <td className="px-3 py-2 font-mono">
                        {r.email ? (
                          <EntityLink kind="user" value={r.email} />
                        ) : (
                          <span className="text-text-muted">No account reported</span>
                        )}
                        {r.account_from ? (
                          <span className="ml-1 font-sans text-xs text-text-muted">
                            from {r.account_from}
                          </span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2">
                        <TierBadge tier={r.tier} />
                      </td>
                      <td className="px-3 py-2 text-text-secondary">{r.evidence}</td>
                      <td className="px-3 py-2 font-mono">
                        {r.devices.map((dev, i) => (
                          <span key={dev}>
                            {i ? ", " : ""}
                            <EntityLink kind="host" value={dev} />
                          </span>
                        ))}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{r.sessions}</td>
                      <td
                        className="whitespace-nowrap px-3 py-2"
                        title={r.last_seen ? `${stamp(r.last_seen)} UTC` : undefined}
                      >
                        {r.last_seen ? since(r.last_seen, now) : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
