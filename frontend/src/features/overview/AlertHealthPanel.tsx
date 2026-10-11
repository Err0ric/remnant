import type { Overview } from "@/lib/api";
import { navigate } from "@/lib/route";
import { Panel } from "./Panel";

interface AlertHealthPanelProps {
  alerts: NonNullable<Overview["alerts"]>;
}

/** Administrators: alert targets whose last send failed, and deliveries that gave up. */
export function AlertHealthPanel({ alerts }: AlertHealthPanelProps) {
  const quiet = alerts.targets.length === 0 && alerts.failed_deliveries === 0;
  return (
    <Panel title="Alert delivery" meta="last 24 hours">
      {quiet ? (
        <p className="text-text-secondary">No failed alert deliveries.</p>
      ) : (
        <>
          {alerts.failed_deliveries > 0 ? (
            <p className="text-danger">
              {alerts.failed_deliveries}{" "}
              {alerts.failed_deliveries === 1 ? "delivery" : "deliveries"} failed after every retry
            </p>
          ) : null}
          <ul className="flex flex-col">
            {alerts.targets.map((t) => (
              <li
                key={t.target_id}
                className="flex flex-col border-t border-border py-1.5 first:border-0"
              >
                <span className="flex items-center gap-2">
                  <button
                    type="button"
                    className="truncate text-left text-accent-text hover:underline"
                    onClick={() => navigate("alerts")}
                  >
                    {t.name}
                  </button>
                  {t.failing ? (
                    <span className="rounded-badge bg-sev-critical-bg px-2 py-px text-xs text-sev-critical-text">
                      Failing
                    </span>
                  ) : null}
                  <span className="ml-auto text-text-secondary">
                    {t.consecutive_failures} in a row
                  </span>
                </span>
                {t.last_error ? <span className="text-text-secondary">{t.last_error}</span> : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}
