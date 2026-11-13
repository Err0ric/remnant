import { useQuery } from "@tanstack/react-query";
import { When } from "@/components/When";
import { api, type InventoryMatch } from "@/lib/api";
import { navigate } from "@/lib/route";
import { seedSearch } from "@/lib/searchSeed";

/** "Proxmox VM 104 build-runner on pve2" (ADR-0045 A5). */
export function guestLabel(m: InventoryMatch): string {
  const kind = m.type === "lxc" ? "container" : "VM";
  return `Proxmox ${kind} ${m.vmid} ${m.name} on ${m.node}`;
}

/** Opens Logs on this guest's inventory events. */
export function showGuestEvents(m: InventoryMatch): void {
  seedSearch({ sql: m.search_sql, range: "30d" });
  navigate("logs");
}

interface InventoryMatchesProps {
  matches: InventoryMatch[];
  /** One line, no times: for table rows. */
  compact?: boolean;
}

/** "matched by name" or "possible match": a name match is never presented as an IP or MAC
 * one (D215). Empty for an IP or MAC match. */
export function matchNote(m: InventoryMatch): string {
  if (m.matched_by !== "name") return "";
  return m.possible ? "possible match" : "matched by name";
}

/** The guests that held an address, each with first and last seen and Show events. */
export function InventoryMatches({ matches, compact }: InventoryMatchesProps) {
  if (!matches.length) return null;
  const possible = matches.some((m) => m.possible);
  if (compact)
    return (
      <div className="flex flex-col text-xs text-text-muted">
        {matches.map((m) => (
          <span key={`${m.source_id}:${m.vmid}`}>
            {guestLabel(m)}
            {matchNote(m) ? ` (${matchNote(m)})` : ""}
          </span>
        ))}
      </div>
    );
  return (
    <div className="flex flex-col gap-1">
      {possible && (
        <p className="text-sm text-text-muted">
          Possible matches: {matches.length} guests are named {matches[0]?.name}
        </p>
      )}
      <InventoryList matches={matches} />
    </div>
  );
}

function InventoryList({ matches }: { matches: InventoryMatch[] }) {
  return (
    <ul aria-label="Proxmox inventory" className="flex flex-col gap-1 text-sm">
      {matches.map((m) => (
        <li key={`${m.source_id}:${m.vmid}`} className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-semibold text-text">{guestLabel(m)}</span>
          {matchNote(m) && !m.possible && (
            <span className="text-xs text-text-muted">{matchNote(m)}</span>
          )}
          <span className="text-text-muted">
            first seen <When iso={m.first_seen} />, last seen <When iso={m.last_seen} />
            {m.current ? "" : " (no longer holds it)"}
          </span>
          <button
            type="button"
            onClick={() => showGuestEvents(m)}
            className="text-accent hover:underline"
          >
            Show events
          </button>
        </li>
      ))}
    </ul>
  );
}

interface InventoryLineProps {
  value: string;
  start: string | undefined;
  /** The end of a Custom range; left out for a window that ends now. */
  end?: string;
}

/** The inventory line on an IP or host page: exact matches only, from the caller's own
 * Proxmox sources; nothing when there is no match. */
export function InventoryLine({ value, start, end }: InventoryLineProps) {
  const q = useQuery({
    queryKey: ["inventory-matches", [value], start, end],
    queryFn: () => api.inventoryMatches([value], start, end),
    staleTime: 60_000,
  });
  return <InventoryMatches matches={q.data?.matches[value] ?? []} />;
}
