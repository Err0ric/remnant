import { EntityLink } from "@/components/EntityLink";
import { kindOf } from "@/features/investigate/entityKind";

interface DeviceRowsProps {
  /** Host names and addresses from the item, told apart by their shape. */
  devices: string[];
  /** How many there were when the item's list was cut (host names are kept first). */
  total?: number | null;
}

/** An alert's devices: host names open the host page, addresses the IP page, each its own
 * row, so an item with no person names both (owner review, item 8). */
export function DeviceRows({ devices, total }: DeviceRowsProps) {
  const addresses = devices.filter((d) => kindOf(d) === "ip");
  const hosts = devices.filter((d) => kindOf(d) !== "ip");
  const cut = total != null && total > devices.length;
  return (
    <>
      {hosts.length ? (
        <>
          <dt className="text-text-muted">Devices</dt>
          <dd className="font-mono">
            {hosts.map((d, i) => (
              <span key={d}>
                {i ? " " : ""}
                <span className="whitespace-nowrap">
                  <EntityLink kind="host" value={d} />
                  {i < hosts.length - 1 ? "," : ""}
                </span>
              </span>
            ))}
          </dd>
        </>
      ) : null}
      {addresses.length ? (
        <>
          <dt className="text-text-muted">Addresses</dt>
          <dd className="font-mono">
            {addresses.map((d, i) => (
              <span key={d}>
                {i ? " " : ""}
                <span className="whitespace-nowrap">
                  <EntityLink kind="ip" value={d} />
                  {i < addresses.length - 1 ? "," : ""}
                </span>
              </span>
            ))}
          </dd>
        </>
      ) : null}
      {cut ? (
        <>
          <dt className="sr-only">Listed</dt>
          <dd className="text-text-secondary">
            {devices.length} of {total} devices and addresses
          </dd>
        </>
      ) : null}
    </>
  );
}
