import type { InventoryItem } from "@/lib/api";

/** Active items of the inventory still to review: the "N to review" count (ADR-0052 3.3),
 * on the Inventory's header and the rail's AI usage count (D258). The same rule as the
 * server's `/api/ai/inventory/count`. */
export function toReview(items: InventoryItem[]): number {
  return items.filter((i) => i.excluded === null && i.status === "unreviewed").length;
}
