/**
 * A one-shot handoff from Discover to a new template draft (ADR-0005: "Edit as draft" from
 * a candidate no template fits). Kept in memory for this tab and taken once by the
 * Templates page; nothing is created until the admin submits the form.
 */
export interface DraftSeed {
  templateId: string;
  path: string;
  glob: string;
}

let seed: DraftSeed | null = null;

export function seedDraft(value: DraftSeed): void {
  seed = value;
}

export function takeDraftSeed(): DraftSeed | null {
  const value = seed;
  seed = null;
  return value;
}
