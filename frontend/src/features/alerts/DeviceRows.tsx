import { EntityLink } from "@/components/EntityLink";
import { kindOf } from "@/features/investigate/entityKind";

interface DeviceRowsProps {
  /** Host names and addresses from the item, told apart by their shape. */
  devices: string[];
}

/** An alert's devices: host names open the host page, addresses the IP page, each its own
 * row, so an item with no person names both (owner review, item 8). */
export function DeviceRows({ devices }: DeviceRowsProps) {
  const addresses = devices.filter((d) => kindOf(d) === "ip");
  const hosts = devices.filter((d) => kindOf(d) !== "ip");
  return (
    <>
      {hosts.length ? (
        <>
          <dt className="text-text-muted">Devices</dt>
          <dd className="font-mono">
            {hosts.map((d, i) => (
              <span key={d}>
                {i ? ", " : ""}
                <EntityLink kind="host" value={d} />
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
                {i ? ", " : ""}
                <EntityLink kind="ip" value={d} />
              </span>
            ))}
          </dd>
        </>
      ) : null}
    </>
  );
}
