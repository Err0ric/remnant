import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { SuggestionRow } from "./SuggestionRow";

/**
 * Suggested groups from template categories and vendors (SPEC 3.6). An approve-only
 * checklist: each suggestion is applied by its own button, only the ticked sources are
 * added, and no one is added to a group here, so nothing grants access by itself.
 */
export function GroupSuggestions() {
  const suggestions = useQuery({
    queryKey: ["group-suggestions"],
    queryFn: api.groupSuggestions,
  });
  const open = (suggestions.data ?? []).filter((s) => s.missing.length > 0);
  if (!open.length) return null;
  return (
    <section aria-label="Suggested groups" className="rounded border border-border p-3">
      <h3 className="text-sm font-semibold">Suggested groups</h3>
      <p className="mb-2 text-sm text-text-secondary">
        From the templates your sources use. Applying one creates the group if needed and adds the
        ticked sources; it never adds people, so it grants no access by itself.
      </p>
      <ul className="flex flex-col gap-2">
        {open.map((s) => (
          <SuggestionRow key={`${s.kind}:${s.key}`} suggestion={s} />
        ))}
      </ul>
    </section>
  );
}
