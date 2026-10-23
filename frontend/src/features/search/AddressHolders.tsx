import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { matchText } from "@/lib/match";

interface AddressHoldersProps {
  ip: string;
  /** The event's time. */
  at: string | null;
}

/** Who had this address when the event happened, and how each was matched: logons,
 * User-ID, GlobalProtect, DHCP leases, and the sign-in that names a machine's person
 * (ADR-0029). Shown only when there is an answer. */
export function AddressHolders({ ip, at }: AddressHoldersProps) {
  const q = useQuery({
    queryKey: ["address", ip, at],
    queryFn: () => api.addressHolders(ip, at ?? undefined),
    staleTime: 300_000,
    retry: false,
  });
  const spans = q.data?.spans ?? [];
  if (!spans.length) return null;
  return (
    <div aria-label={`Who had ${ip}`} className="mb-2 text-sm">
      <p className="text-text-secondary">
        At that time <span className="font-mono">{ip}</span> was held by:
      </p>
      <ul className="ml-4 list-disc text-text-secondary">
        {spans.slice(0, 5).map((s, i) => (
          <li key={i} title={`From ${s.source}`}>
            <span className="text-text">{matchText(s)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
