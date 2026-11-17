import { ChevronDown } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api, type TemplateChange } from "@/lib/api";
import { stamp } from "@/features/overview/time";

/** Changes this recent are announced on the Sources page. */
const RECENT_DAYS = 30;

function day(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Parser updates (F66, D121): one line, and the detail in a collapsed "What changed" in
 * plain words (fix list 2026-11-16 item 23). Updates apply to events received from the day
 * shown; stored events keep how they were read, so searches that filter on a changed detail
 * are named to check before comparing with earlier days. Admins only (the endpoint is). */
export function MappingChanges() {
  const changes = useQuery({ queryKey: ["template-changes"], queryFn: api.templateChanges });
  const cutoff = Date.now() - RECENT_DAYS * 86400_000;
  const recent = (Array.isArray(changes.data) ? changes.data : []).filter(
    (c) => c.current && c.since !== null && Date.parse(c.since) >= cutoff,
  );
  if (recent.length === 0) return null;
  const parsers = new Set(recent.map((c) => c.template_id)).size;
  const affected = new Map(
    recent.flatMap((c) => c.affected.map((a) => [`${a.kind}:${a.id}`, a] as const)),
  );
  return (
    <details
      aria-label="Parser updates"
      className="group rounded-card border border-border bg-surface text-sm"
    >
      <summary className="flex cursor-pointer list-none [&::-webkit-details-marker]:hidden flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2">
        {/* The selects' chevron (14px, --text-secondary), pointing right while closed; no
            animation, so it is never caught mid-turn. */}
        <ChevronDown
          size={14}
          strokeWidth={1.5}
          aria-hidden
          className="shrink-0 -rotate-90 text-text-secondary group-open:rotate-0"
        />
        <span>
          {plural(parsers, "parser", "parsers")} updated in the last {RECENT_DAYS} days; earlier
          events keep how they were read.
        </span>
        {affected.size ? (
          <span className="text-warn">{plural(affected.size, "search", "searches")} to check</span>
        ) : null}
        <span className="text-accent-text">What changed</span>
      </summary>
      <ul className="flex flex-col gap-2 border-t border-border px-3 py-2">
        {recent.map((c) => (
          <Change key={`${c.template_id}-${c.version}`} change={c} />
        ))}
      </ul>
    </details>
  );
}

interface ChangeProps {
  change: TemplateChange;
}

function Change({ change: c }: ChangeProps) {
  return (
    <li className="flex flex-col gap-0.5">
      <span>
        <span className="font-semibold">{c.template_name}</span>
        {c.since ? (
          <span className="text-text-secondary" title={`${stamp(c.since)} UTC`}>
            , from {day(c.since)}
          </span>
        ) : null}
      </span>
      <span className="text-text-secondary">
        {c.summary || "Reads these records differently from that day."}
      </span>
      {c.affected.length > 0 ? (
        <span className="text-warn">
          Check before comparing with earlier days:{" "}
          {c.affected.map((a) => `${a.kind} "${a.name}"`).join("; ")}
        </span>
      ) : null}
    </li>
  );
}
