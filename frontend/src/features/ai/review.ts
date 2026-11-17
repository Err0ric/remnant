import { api, type AiInventory } from "@/lib/api";
import { useRailCount } from "@/lib/railCount";

/** The Inventory's two numbers for the page and the rail, counted by the server (one rule,
 * on `/api/ai/inventory` and `/api/ai/inventory/count`). */
export interface InventoryCounts {
  /** Active items nobody has marked Approved or Not approved: "N to review" (D258). */
  toReview: number;
  /** Active items marked Not approved. */
  notApproved: number;
}

/** The Inventory's header, AI usage's Needs attention line, and the rail all read these
 * here, so they always show the same numbers. They follow the Inventory a page loaded;
 * elsewhere the count, which is not audited. Both keys sit under ["ai-usage"], which every
 * review invalidates, so a review changes all of them at once. Null while not known yet. */
export function useAiInventoryCounts(immediate = false): InventoryCounts | null {
  return useRailCount<AiInventory, { to_review: number; not_approved?: number }, InventoryCounts>(
    ["ai-usage", "inventory"],
    () => api.aiInventory(30),
    ["ai-usage", "inventory", "count"],
    api.aiInventoryCount,
    (p) => ({ toReview: p.to_review ?? 0, notApproved: p.not_approved ?? 0 }),
    (c) => ({ toReview: c.to_review, notApproved: c.not_approved ?? 0 }),
    { toReview: 0, notApproved: 0 },
    immediate,
  );
}
