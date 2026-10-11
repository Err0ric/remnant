import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// Teach tailwind-merge about the custom font-size scale (DESIGN.md section 2) so
// text-md is treated as a size and not confused with text-<color> tokens.
const twMerge = extendTailwindMerge({
  extend: { classGroups: { "font-size": [{ text: ["md", "kpi"] }] } },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
