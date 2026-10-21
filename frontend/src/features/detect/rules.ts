import type { SigmaRule, SigmaRuleListed } from "@/lib/api";

/** Attribution text for a rule (Detection Rule License 1.1 requires it with every match). */
export function authorText(author: string): string {
  return author.trim() || "author not stated";
}

export function logsourceText(r: Pick<SigmaRule, "product" | "service" | "category">): string {
  return [r.product, r.service, r.category].filter(Boolean).join(" / ");
}

export interface RuleFilter {
  text: string;
  enabledOnly: boolean;
  /** Only rules some source the caller can read would run on. */
  withDataOnly: boolean;
}

/** Case-insensitive match on title, author, id, tags, and logsource. */
export function filterRules(rules: SigmaRuleListed[], f: RuleFilter): SigmaRuleListed[] {
  const needle = f.text.trim().toLowerCase();
  return rules.filter((r) => {
    if (f.enabledOnly && !r.enabled) return false;
    if (f.withDataOnly && !r.source_ids.length) return false;
    if (!needle) return true;
    return [r.title, r.author, r.rule_id, logsourceText(r), ...r.tags].some((v) =>
      v.toLowerCase().includes(needle),
    );
  });
}
