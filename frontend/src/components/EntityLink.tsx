import type { MouseEvent } from "react";
import {
  entityHref,
  isEntityValue,
  openEntity,
  type EntityKind,
  type EntityTab,
} from "@/lib/entity";
import { cn } from "@/lib/cn";
import { Truncate } from "@/components/Truncate";
import { kindOf } from "@/features/investigate/entityKind";

interface EntityLinkProps {
  kind: EntityKind;
  value: unknown;
  /** Shown instead of the value (for example a service's name for its id). */
  label?: string;
  className?: string;
  /** A person opens on this tab (AI usage and Agents open "AI use", D189). */
  tab?: EntityTab;
  /** Said after the value on hover ("US · AS64501", an address's place). */
  hint?: string;
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
export function EntityLink({ kind, value, label, className, tab, hint }: EntityLinkProps) {
  if (!isEntityValue(value))
    return <span className={className}>{label ?? String(value ?? "")}</span>;
  const entity = { kind, value };
  const text = label ?? String(value);
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
      // The full value first: a long one is cut in the cell (DESIGN.md section 7, D257).
      title={`${text}${hint ? `, ${hint}` : ""}\nInvestigate this ${NOUN[kind]}`}
      aria-label={text}
      className={cn("group text-accent-text hover:underline focus-visible:underline", className)}
    >
      <Truncate
        value={text}
        kind={kind === "user" && text.includes("@") ? "email" : "name"}
        inLink
        // An underline does not reach into the row's two parts from the link.
        className="group-hover:underline group-focus-visible:underline"
      />
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
        // The comma stays with the value before it: a line never starts with one.
        <span key={`${e.kind}:${e.value}`}>
          {i ? " " : ""}
          <span className="whitespace-nowrap">
            <EntityLink kind={e.kind} value={e.value} tab={e.kind === "user" ? tab : undefined} />
            {i < items.length - 1 ? "," : ""}
          </span>
        </span>
      ))}
    </>
  );
}
