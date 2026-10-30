import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/** Changes this recent are announced on the Sources page. */
const RECENT_DAYS = 30;

/** Template updates apply to events received after the update; stored events keep the
 * mapping they were parsed with. Says from which day, and which searches filter on a
 * column whose meaning changed (F66). */
export function MappingChanges() {
  const changes = useQuery({ queryKey: ["template-changes"], queryFn: api.templateChanges });
  const cutoff = Date.now() - RECENT_DAYS * 86400_000;
  const recent = (Array.isArray(changes.data) ? changes.data : []).filter(
    (c) => c.current && c.since !== null && Date.parse(c.since) >= cutoff,
  );
  if (recent.length === 0) return null;
  return (
    <section
      aria-label="Parser updates"
      className="rounded-card border border-border bg-surface px-3 py-2 text-sm"
    >
      <h2 className="font-semibold">Parser updates</h2>
      <p className="text-text-secondary">
        Updated parsers apply to events received from the day shown. Earlier events keep the mapping
        they were stored with.
      </p>
      <ul className="mt-2 flex flex-col gap-2">
        {recent.map((c) => (
          <li key={`${c.template_id}-${c.version}`} className="flex flex-col gap-0.5">
            <span>
              <span className="font-mono">{c.template_id}</span> {c.version}, from{" "}
              <span className="font-mono">{c.since?.slice(0, 10)}</span>: {c.note}
            </span>
            {c.affected.length > 0 ? (
              <span className="text-warn">
                Check before comparing with earlier days:{" "}
                {c.affected.map((a) => `${a.kind} "${a.name}" (${a.fields.join(", ")})`).join("; ")}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
