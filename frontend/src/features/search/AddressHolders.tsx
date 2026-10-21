import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface AddressHoldersProps {
  ip: string;
  /** The event's time; the lookup covers the 12 hours up to it. */
  at: string | null;
}

/** Who had this address when the event happened, from logon and User-ID events
 * (ADR-0020 row 1). Shown only when there is an answer. */
export function AddressHolders({ ip, at }: AddressHoldersProps) {
  const q = useQuery({
    queryKey: ["address", ip, at],
    queryFn: () => api.addressHolders(ip, at ?? undefined),
    staleTime: 300_000,
    retry: false,
  });
  const users = (q.data?.holders ?? []).filter((h) => h.kind === "user").slice(0, 2);
  const hosts = (q.data?.holders ?? []).filter((h) => h.kind === "host").slice(0, 2);
  if (!users.length && !hosts.length) return null;
  return (
    <p className="mb-2 text-sm text-text-secondary">
      At that time <span className="font-mono">{ip}</span> was{" "}
      {users.length ? (
        <span className="font-mono text-text">{users.map((u) => u.name).join(" or ")}</span>
      ) : (
        "an unnamed user"
      )}
      {hosts.length ? (
        <>
          {" "}
          on <span className="font-mono text-text">{hosts.map((h) => h.name).join(" or ")}</span>
        </>
      ) : null}
      <span className="text-text-muted"> (from logon and User-ID events)</span>
    </p>
  );
}
