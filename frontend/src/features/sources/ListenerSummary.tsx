import type { ListenerStatus, SyslogSettings } from "@/lib/api";
import { since } from "@/features/overview/time";

interface ListenerSummaryProps {
  settings: SyslogSettings | null;
  listener: ListenerStatus | null;
}

const PROTOCOL: Record<string, string> = { udp: "UDP", tcp: "TCP", tls: "TLS" };

// Docker's default bridge gateways (172.16.0.0/12, host part .1): what senders look like
// when Docker rewrites their addresses (ADR-0021, docs/install/syslog-listener.md).
const GATEWAY = /^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.1$/;

function behindNat(addresses: string[]): boolean {
  return addresses.length > 0 && addresses.every((a) => GATEWAY.test(a));
}

/** Where a syslog listener source listens, and who has sent to it (ADR-0021). */
export function ListenerSummary({ settings, listener }: ListenerSummaryProps) {
  const protocol = listener?.protocol ?? settings?.protocol ?? "udp";
  const port = listener?.port ?? settings?.port;
  const refused = listener?.dropped_not_allowed ?? 0;
  const full = listener?.dropped_full ?? 0;
  return (
    <div className="flex min-w-48 flex-col gap-0.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="whitespace-nowrap rounded-badge bg-sev-info-bg px-2 py-px text-xs font-normal text-text-secondary">
          Syslog {PROTOCOL[protocol] ?? protocol}
        </span>
        <span>port {port}</span>
      </div>
      {listener ? (
        <div className="font-sans text-sm text-text-secondary">
          {listener.received.toLocaleString()} received
          {refused ? `, ${refused.toLocaleString()} refused` : ""}
          {full ? `, ${full.toLocaleString()} dropped (spool full)` : ""}
          {listener.connections ? `, ${listener.connections} connected` : ""}
        </div>
      ) : (
        <div className="font-sans text-sm text-text-muted">Starts within a few seconds</div>
      )}
      {settings ? (
        <div className="font-sans text-sm text-text-muted">
          {settings.allowed_senders.length
            ? `Accepts ${settings.allowed_senders.join(", ")}`
            : "Accepts private networks only"}
        </div>
      ) : null}
      {listener && behindNat(listener.senders.map((x) => x.address)) ? (
        <p role="note" className="font-sans text-sm text-warn">
          Every sender shows as a Docker gateway address, so the allowed-senders rule cannot tell
          devices apart. See docs/install/syslog-listener.md, step 2.
        </p>
      ) : null}
      {listener && listener.senders.length > 0 ? (
        <details className="font-sans text-sm">
          <summary className="cursor-pointer text-text-secondary hover:text-text">
            Senders ({listener.senders.length})
          </summary>
          <ul className="mt-1 flex flex-col gap-0.5" aria-label="Senders">
            {listener.senders.map((s) => (
              <li key={s.address} className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-mono">{s.address}</span>
                {s.allowed ? null : (
                  <span className="rounded-badge bg-sev-critical-bg px-1.5 text-xs text-sev-critical-text">
                    Refused
                  </span>
                )}
                <span className="text-text-secondary">
                  {s.count.toLocaleString()} {s.allowed ? "messages" : "refused"}
                  {s.last_seen ? `, ${since(s.last_seen, new Date().toISOString())}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
