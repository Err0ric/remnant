import { EntityLink } from "@/components/EntityLink";
import type { DevicePerson } from "@/lib/api";

interface DevicePeopleProps {
  found: DevicePerson[];
}

const HOW: Record<DevicePerson["how"], string> = {
  hooks: "seen on this host in the hooks plugin",
  hooks_identities: "seen on this host in the hooks plugin (names linked in Identities)",
};

/** Who used a device the alert names, and how that was found (owner item 5). Several
 * people on the host are "Possible" with the count; none of them is picked (ADR-0048 C1). */
export function DevicePeople({ found }: DevicePeopleProps) {
  if (!found.length) return null;
  return (
    <>
      <dt className="text-text-muted">Person on device</dt>
      <dd className="grid gap-0.5">
        {found.map((f) => (
          <span key={f.device}>
            <span className="font-mono">{f.device}</span>
            {": "}
            {f.level === "possible" ? "Possible: " : null}
            {f.people.map((p, i) => (
              <span key={p}>
                {i ? (i === f.people.length - 1 ? " or " : ", ") : ""}
                <EntityLink kind="user" value={p} tab="ai" />
              </span>
            ))}
            {f.count > f.people.length ? ` and ${f.count - f.people.length} more` : null}
            <span className="text-text-secondary">
              {f.level === "possible" ? `, ${f.count} people ${HOW[f.how]}` : `, ${HOW[f.how]}`}
            </span>
          </span>
        ))}
      </dd>
    </>
  );
}
