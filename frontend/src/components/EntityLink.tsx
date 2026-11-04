import type { MouseEvent } from "react";
import {
  entityHref,
  isEntityValue,
  openEntity,
  type EntityKind,
  type EntityTab,
} from "@/lib/entity";
import { cn } from "@/lib/cn";
import { kindOf } from "@/features/investigate/entityKind";

interface EntityLinkProps {
  kind: EntityKind;
  value: unknown;
  /** Shown instead of the value (for example a service's name for its id). */
  label?: string;
  className?: string;
  /** A person opens on this tab (AI usage and Agents open "AI use", D189). */
  tab?: EntityTab;
}

const NOUN: Record<EntityKind, string> = {
  ip: "address",
  user: "person",
  host: "machine",
  service: "AI service",
};

/** Every IP, user, host, and AI service value, everywhere, opens its page in
 * Investigations (product pass step 2). A real link: middle-click and copy work. Empty
 * values and placeholders stay text. */
export function EntityLink({ kind, value, label, className, tab }: EntityLinkProps) {
  if (!isEntityValue(value))
    return <span className={className}>{label ?? String(value ?? "")}</span>;
  const entity = { kind, value };
  const open = (e: MouseEvent<HTMLAnchorElement>) => {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    e.stopPropagation(); // a link inside a row opens the entity, not the row
    openEntity(entity, tab);
  };
  return (
    <a
      href={entityHref(entity, tab)}
      onClick={open}
      // Enter on the link opens the entity, not a clickable row around it.
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") e.stopPropagation();
      }}
      title={`Investigate this ${NOUN[kind]}`}
      className={cn(
        "text-accent-text [overflow-wrap:anywhere] hover:underline focus-visible:underline",
        className,
      )}
    >
      {label ?? value}
    </a>
  );
}

interface EntityListProps {
  /** People are users; machines are addresses or host names, told apart by their shape. */
  people?: string[];
  machines?: string[];
  empty?: string;
  /** People open on this tab (AI usage: AI activity). */
  tab?: EntityTab;
}

/** A comma list of people or machines, each a link (AI usage's Who column). */
export function EntityList({ people = [], machines = [], empty = "·", tab }: EntityListProps) {
  const items: { kind: EntityKind; value: string }[] = people.length
    ? people.map((value) => ({ kind: "user", value }))
    : machines.map((value) => ({ kind: kindOf(value) === "ip" ? "ip" : "host", value }));
  if (!items.length) return <>{empty}</>;
  return (
    <>
      {items.map((e, i) => (
        <span key={`${e.kind}:${e.value}`}>
          {i ? ", " : ""}
          <EntityLink kind={e.kind} value={e.value} tab={e.kind === "user" ? tab : undefined} />
        </span>
      ))}
    </>
  );
}
